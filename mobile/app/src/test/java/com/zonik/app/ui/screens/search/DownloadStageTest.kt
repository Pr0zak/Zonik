package com.zonik.app.ui.screens.search

import com.zonik.app.data.api.JobProgress
import org.junit.Assert.assertEquals
import org.junit.Test

class DownloadStageTest {
    private val queued = GetButtonState(state = GetState.Searching, jobId = "j")

    private fun resolve(p: JobProgress) = queued.resolve(p)

    @Test fun pendingJobWaitsForSlot() {
        val s = resolve(JobProgress("j", status = "pending"))
        assertEquals(GetState.Searching, s.state)
        assertEquals("Queued", s.label)
    }

    @Test fun runningWithoutTransferIsFindingSource() {
        assertEquals("Finding", resolve(JobProgress("j", status = "running")).label)
    }

    @Test fun peerQueueIsWaiting() {
        val s = resolve(JobProgress("j", status = "running", transferState = "queued"))
        assertEquals("Waiting", s.label)
    }

    @Test fun transferringShowsSpeedAndEta() {
        val s = resolve(JobProgress("j", status = "running", transferState = "transferring",
            progress = 50, total = 100, pct = 50f, speedBps = 2 * 1_048_576L, etaSeconds = 75))
        assertEquals(GetState.Downloading, s.state)
        assertEquals("2.0 MB/s · 1m 15s left", s.detail)
    }

    @Test fun transferDoneButJobRunningIsImporting() {
        assertEquals("Adding", resolve(JobProgress("j", status = "running", transferState = "completed")).label)
    }

    @Test fun completedCarriesTrackId() {
        val s = resolve(JobProgress("j", status = "completed", trackId = "t1", alreadyInLibrary = true))
        assertEquals(GetState.Done, s.state)
        assertEquals("t1", s.trackId)
        assertEquals("Already in your library", s.detail)
    }

    @Test fun failedCarriesReason() {
        val s = resolve(JobProgress("j", status = "failed", error = "All 3 sources failed: Peer did not respond in time"))
        assertEquals(GetState.Failed, s.state)
        assertEquals("All 3 sources failed: Peer did not respond in time", s.error)
    }
}
