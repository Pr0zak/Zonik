package com.zonik.core.auth

import com.zonik.core.model.ServerConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.builtins.ListSerializer
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Outcome of an auth/pairing call. Never throws for HTTP or network failures. */
sealed interface AuthResult<out T> {
    data class Ok<T>(val value: T) : AuthResult<T>

    /** The server answered with a non-2xx status; [message] is its `detail` when it sent one. */
    data class Http(val code: Int, val message: String?) : AuthResult<Nothing>

    /** No usable answer: network error, timeout, or a body that could not be parsed. */
    data class Failure(val error: Throwable) : AuthResult<Nothing>

    fun valueOrNull(): T? = (this as? Ok<T>)?.value
}

/** A one-line, user-facing description of a failed [AuthResult]. */
fun AuthResult<*>.describe(): String = when (this) {
    is AuthResult.Ok -> "OK"
    is AuthResult.Http -> message ?: when (code) {
        401 -> "Not signed in"
        403 -> "Not allowed"
        404 -> "Not found"
        else -> "Server returned $code"
    }
    is AuthResult.Failure -> when (error) {
        is java.net.UnknownHostException -> "Server not found"
        is java.net.ConnectException -> "Can't connect to the server"
        is java.net.SocketTimeoutException -> "The server didn't answer in time"
        else -> error.message ?: error.javaClass.simpleName
    }
}

/**
 * Plain-OkHttp client for Zonik's /api/auth/… and /api/pair/… endpoints. Works before there is
 * a saved config (Retrofit's base URL is a placeholder until login), so every call takes the
 * server URL explicitly; signed-in calls take the [ServerConfig] and sign with [SubsonicAuth].
 * Shared by the phone/TV app and the watch.
 */
class ZonikAuthClient(
    private val http: OkHttpClient = defaultClient(),
    private val clientName: String = "ZonikApp",
) {

    // --- public ---

    suspend fun status(serverUrl: String): AuthResult<AuthStatus> =
        call(get(join(serverUrl, "/api/auth/status")), AuthStatus.serializer())

    suspend fun deviceLogin(
        serverUrl: String,
        username: String,
        password: String,
        label: String?,
        platform: String?,
    ): AuthResult<DeviceLoginResponse> = call(
        post(join(serverUrl, "/api/auth/device"),
            encode(DeviceLoginRequest.serializer(), DeviceLoginRequest(username, password, label, platform))),
        DeviceLoginResponse.serializer(),
    )

    suspend fun createPair(serverUrl: String, label: String?, platform: String?): AuthResult<PairCodeResponse> = call(
        post(join(serverUrl, "/api/pair"), encode(PairCreateRequest.serializer(), PairCreateRequest(label, platform))),
        PairCodeResponse.serializer(),
    )

    suspend fun pollPair(serverUrl: String, code: String): AuthResult<PairPollResponse> =
        call(get(join(serverUrl, "/api/pair/${code.trim()}")), PairPollResponse.serializer())

    // --- signed in (any real credentials: device token or legacy key) ---

    suspend fun issueDeviceToken(config: ServerConfig, label: String?, platform: String?): AuthResult<DeviceTokenResponse> =
        call(
            post(signed(config, "/api/auth/devices"),
                encode(DeviceTokenRequest.serializer(), DeviceTokenRequest(label, platform))),
            DeviceTokenResponse.serializer(),
        )

    suspend fun me(config: ServerConfig): AuthResult<AuthUser> =
        call(get(signed(config, "/api/auth/me")), AuthUser.serializer())

    suspend fun listDevices(config: ServerConfig): AuthResult<List<DeviceItem>> =
        call(get(signed(config, "/api/auth/devices")), ListSerializer(DeviceItem.serializer()))

    suspend fun revokeDevice(config: ServerConfig, id: String): AuthResult<Unit> =
        callUnit(Request.Builder().url(signed(config, "/api/auth/devices/$id")).delete().build())

    suspend fun pairInfo(config: ServerConfig, code: String): AuthResult<PairInfo> =
        call(get(signed(config, "/api/pair/${code.trim()}/info")), PairInfo.serializer())

    suspend fun approvePair(config: ServerConfig, code: String, label: String? = null): AuthResult<PairApproveResponse> =
        call(
            post(signed(config, "/api/pair/${code.trim()}/approve"),
                encode(PairApproveRequest.serializer(), PairApproveRequest(label))),
            PairApproveResponse.serializer(),
        )

    // --- plumbing ---

    private fun signed(config: ServerConfig, path: String): String =
        SubsonicAuth.appendTo(join(config.url, path), config, clientName)

    private fun get(url: String): Request = Request.Builder().url(url).get().build()

    private fun post(url: String, body: RequestBody): Request = Request.Builder().url(url).post(body).build()

    private fun <T> encode(serializer: KSerializer<T>, value: T): RequestBody =
        AuthJson.json.encodeToString(serializer, value).toRequestBody(JSON)

    private suspend fun <T> call(request: Request, serializer: KSerializer<T>): AuthResult<T> =
        withContext(Dispatchers.IO) {
            try {
                http.newCall(request).execute().use { response ->
                    val body = response.body?.string()
                    if (!response.isSuccessful) {
                        AuthResult.Http(response.code, AuthJson.errorDetail(body))
                    } else {
                        AuthResult.Ok(AuthJson.json.decodeFromString(serializer, body ?: ""))
                    }
                }
            } catch (e: IOException) {
                AuthResult.Failure(e)
            } catch (e: IllegalArgumentException) { // bad URL, or a body that is not the expected JSON
                AuthResult.Failure(e)
            }
        }

    private suspend fun callUnit(request: Request): AuthResult<Unit> = withContext(Dispatchers.IO) {
        try {
            http.newCall(request).execute().use { response ->
                if (response.isSuccessful) AuthResult.Ok(Unit)
                else AuthResult.Http(response.code, AuthJson.errorDetail(response.body?.string()))
            }
        } catch (e: IOException) {
            AuthResult.Failure(e)
        } catch (e: IllegalArgumentException) {
            AuthResult.Failure(e)
        }
    }

    companion object {
        private val JSON = "application/json".toMediaType()

        fun join(serverUrl: String, path: String): String = serverUrl.trim().trimEnd('/') + path

        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(8, TimeUnit.SECONDS)
            .readTimeout(15, TimeUnit.SECONDS)
            .build()
    }
}
