package com.zonik.app.data.api

import org.json.JSONObject
import retrofit2.HttpException
import java.io.IOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException

/**
 * A sentence a listener can act on, instead of "HTTP 500 Internal Server Error"
 * or a raw exception. For HTTP errors it prefers the server's own message
 * (FastAPI's `detail`, or the `error`/`message` field Zonik's endpoints use).
 */
fun friendlyError(e: Throwable): String = when (e) {
    is HttpException -> serverMessage(e) ?: when (e.code()) {
        401, 403 -> "The server refused the request — check your login in Settings"
        404 -> "The server doesn't support this yet — it may need updating"
        in 500..599 -> "The server hit an error (${e.code()})"
        else -> "The server answered ${e.code()}"
    }
    is SocketTimeoutException -> "The server took too long to answer"
    is UnknownHostException, is ConnectException -> "Can't reach your Zonik server"
    is IOException -> "Network problem: ${e.message ?: "connection lost"}"
    else -> e.message ?: "Something went wrong"
}

private fun serverMessage(e: HttpException): String? = try {
    val body = e.response()?.errorBody()?.string().orEmpty()
    if (body.isBlank()) null else {
        val obj = JSONObject(body)
        listOf("detail", "error", "message")
            .firstNotNullOfOrNull { k -> obj.optString(k).takeIf { it.isNotBlank() && it != "null" } }
    }
} catch (_: Exception) {
    null
}
