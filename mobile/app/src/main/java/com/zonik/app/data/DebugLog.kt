package com.zonik.app.data

import android.content.Context
import java.io.File
import java.io.FileOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.ConcurrentLinkedDeque
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.launch

object DebugLog {
    private val entries = ConcurrentLinkedDeque<String>()
    private const val MAX_ENTRIES = 500
    private const val MAX_FILE_SIZE = 512 * 1024L // 512 KB
    private const val MAX_STAGED = 5000
    private const val LOG_FILE = "debug_log.txt"
    private const val PREV_LOG_FILE = "debug_log_prev.txt"
    private val timeFormat = ThreadLocal.withInitial { SimpleDateFormat("HH:mm:ss.SSS", Locale.US) }
    private val dateTimeFormat = ThreadLocal.withInitial { SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.US) }
    // Reassigned by rotateIfNeeded() from the writer coroutine, read from every thread.
    @Volatile private var logFile: File? = null
    private var initialized = false

    // Disk writes never happen on the caller's thread — on the TV that caller is
    // often the main thread mid-key-handling, competing with the ExoPlayer cache
    // for the same slow flash. Lines queue here and one IO coroutine drains them.
    // The channel is unbounded so a log call can never block; anything logged
    // before init() simply waits in the queue until the consumer starts.
    private val fileQueue = Channel<String>(Channel.UNLIMITED)
    private var writerScope: CoroutineScope? = null
    // Serializes the two threads that ever touch the file: the writer coroutine and the
    // crashing thread.
    private val fileLock = Any()
    // Lines live here from the moment they leave the channel until the moment they are on
    // disk. Publishing only the finished batch left a window where a line was in neither
    // place, and those are precisely the lines a crash report needs.
    private val staged = java.util.concurrent.ConcurrentLinkedQueue<String>()

    /**
     * Initialize file-based logging and install crash handler.
     * Call from Application.onCreate().
     */
    fun init(context: Context) {
        if (initialized) return
        initialized = true

        val dir = context.filesDir
        logFile = File(dir, LOG_FILE)

        // Rotate if previous log is too large
        rotateIfNeeded()

        // Load previous session entries into memory for display
        loadFromFile()

        startWriter()

        // Mark session start
        val sessionLine = "--- Session start ${dateTimeFormat.get()!!.format(Date())} ---"
        appendToFile(sessionLine)
        entries.addLast(sessionLine)

        // Install uncaught exception handler
        val defaultHandler = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            try {
                val crash = buildString {
                    appendLine("!!! CRASH on thread '${thread.name}' !!!")
                    appendLine("${throwable.javaClass.name}: ${throwable.message}")
                    throwable.stackTrace.take(30).forEach { appendLine("    at $it") }
                    var cause = throwable.cause
                    while (cause != null) {
                        appendLine("Caused by: ${cause.javaClass.name}: ${cause.message}")
                        cause.stackTrace.take(15).forEach { appendLine("    at $it") }
                        cause = cause.cause
                    }
                }
                val time = timeFormat.get()!!.format(Date())
                val line = "$time E/CRASH: $crash"
                // The process is about to die, so the writer coroutine may never
                // run again — this one write has to happen inline.
                flushBlocking(line)
            } catch (_: Exception) {
                // Best effort — don't make crash handling worse
            }
            defaultHandler?.uncaughtException(thread, throwable)
        }
    }

    // Redacts secret query-param values (auth token, salt, user, password, apiKey)
    // from any string containing a URL. UNCONDITIONAL — tokens must never reach
    // the log file or logcat, even in debug-variant builds that get uploaded via /api/logs.
    private val secretParamRegex = Regex("(?i)([?&](?:t|s|u|p|salt|token|apiKey)=)[^&\\s]*")

    fun sanitizeUrl(s: String?): String {
        if (s == null) return ""
        return secretParamRegex.replace(s) { "${it.groupValues[1]}***" }
    }

    fun d(tag: String, message: String) {
        add("D", tag, message)
        android.util.Log.d(tag, message)
    }

    fun e(tag: String, message: String, error: Throwable? = null) {
        val msg = if (error != null) "$message: ${error.message}" else message
        add("E", tag, msg)
        android.util.Log.e(tag, message, error)
    }

    fun w(tag: String, message: String) {
        add("W", tag, message)
        android.util.Log.w(tag, message)
    }

    private fun add(level: String, tag: String, message: String) {
        val time = timeFormat.get()!!.format(Date())
        val line = "$time $level/$tag: $message"
        entries.addLast(line)
        while (entries.size > MAX_ENTRIES) {
            entries.pollFirst()
        }
        appendToFile(line)
    }

    fun getAll(): String {
        return entries.joinToString("\n")
    }

    /**
     * Returns all persisted logs including previous sessions and crash data.
     */
    fun getPersistedLogs(): String {
        val file = logFile ?: return getAll()
        return try {
            if (file.exists()) file.readText() else getAll()
        } catch (_: Exception) {
            getAll()
        }
    }

    /**
     * Returns previous session's logs (useful for post-crash analysis).
     */
    fun getPreviousSessionLogs(): String? {
        val dir = logFile?.parentFile ?: return null
        val prev = File(dir, PREV_LOG_FILE)
        return try {
            if (prev.exists()) prev.readText() else null
        } catch (_: Exception) {
            null
        }
    }

    fun clear() {
        entries.clear()
        logFile?.delete()
    }

    private fun appendToFile(line: String) {
        try {
            fileQueue.trySend(line)
        } catch (_: Exception) {
            // Best effort — a log call must never throw at its caller
        }
    }

    /**
     * Rolls debug_log.txt to debug_log_prev.txt once it passes [MAX_FILE_SIZE]. Called from
     * init() and after every batch — checking only at startup let a long-lived session (which
     * a TV now is, since the activity no longer tears the process down) grow the file without
     * any bound. One File.length() per batch, not per line, because the writer coalesces.
     */
    private fun rotateIfNeeded() {
        val file = logFile ?: return
        if (!file.exists() || file.length() <= MAX_FILE_SIZE) return
        val dir = file.parentFile ?: return
        val prev = File(dir, PREV_LOG_FILE)
        prev.delete()
        file.renameTo(prev)
        logFile = File(dir, LOG_FILE)
    }

    private fun startWriter() {
        if (writerScope != null) return
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        writerScope = scope
        scope.launch {
            for (first in fileQueue) {
                // Staged before anything else can observe the dequeue.
                staged.add(first)
                // Whatever piled up while the last write was in flight goes out
                // in the same open/write/close instead of one per line.
                drainQueueToStaged()
                flushStaged(null)
            }
        }
    }

    private fun drainQueueToStaged() {
        while (true) {
            val next = fileQueue.tryReceive().getOrNull() ?: break
            staged.add(next)
            // A write that keeps failing (no log file yet) must not grow without bound.
            if (staged.size > MAX_STAGED) staged.poll()
        }
    }

    /**
     * Drains anything still queued and writes it together with [line] on the
     * calling thread. Only for the crash path, where the process won't survive
     * long enough for the writer coroutine to get scheduled.
     */
    private fun flushBlocking(line: String) {
        try {
            drainQueueToStaged()
            flushStaged(line)
        } catch (_: Exception) {
            // Best effort
        }
    }

    /**
     * The file has exactly one writer at a time. Without the lock the crashing thread and the
     * writer coroutine can interleave inside the same append stream, or one can rotate the file
     * out from under the other's open handle — landing a batch in the log that
     * [rotateIfNeeded] is about to overwrite as the previous session.
     */
    /**
     * Writes everything staged, plus [extra], and only then drops those lines from the staging
     * queue — so a line is always either in the channel, in [staged], or on disk, and a crash
     * mid-write loses nothing. The lock gives the file a single writer: without it the crashing
     * thread and the writer coroutine can interleave inside the same append stream, or one can
     * rotate the file out from under the other's open handle.
     */
    private fun flushStaged(extra: String?) {
        synchronized(fileLock) {
            val file = logFile ?: return
            val lines = staged.toList()
            if (lines.isEmpty() && extra == null) return
            val text = buildString {
                lines.forEach { append(it).append('\n') }
                if (extra != null) append(extra).append('\n')
            }
            try {
                FileOutputStream(file, true).bufferedWriter().use { it.write(text) }
                // Only what we actually wrote. Nothing else removes from `staged`, and both
                // removers hold this lock, so the poll count lines up with the snapshot.
                repeat(lines.size) { staged.poll() }
                rotateIfNeeded()
            } catch (_: Exception) {
                // Best effort — the lines stay staged for the next attempt
            }
        }
    }

    private fun loadFromFile() {
        try {
            val file = logFile ?: return
            if (!file.exists()) return
            val lines = file.readLines()
            // Load last MAX_ENTRIES lines into memory
            lines.takeLast(MAX_ENTRIES).forEach { entries.addLast(it) }
        } catch (_: Exception) {
            // Best effort
        }
    }
}
