package com.zonik.core.api

import android.util.Log
import com.zonik.core.auth.SubsonicAuth
import kotlinx.coroutines.runBlocking
import okhttp3.Interceptor
import okhttp3.Response

/**
 * Appends auth query params to every outgoing request, using the current ServerConfig from
 * the host module: `apiKey` when the config holds a device token, else Subsonic u/t/s (see
 * [SubsonicAuth]), plus v, c and f=json.
 *
 * A URL that already carries credentials (a stream or cover URL built with [SubsonicAuth]) is
 * left signed as it is — adding a second set could mix `apiKey` with `u`/`t`/`s`, which an
 * OpenSubsonic server rejects. Parameters the URL already has are never duplicated.
 *
 * Stays out of Hilt — both :app and :wear construct this directly. The
 * caller controls the client identifier (`c=` param) so wear can identify
 * itself separately if we want per-device usage stats.
 */
class SubsonicAuthInterceptor(
    private val configProvider: ServerConfigProvider,
    private val clientName: String = "ZonikApp",
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val config = runBlocking { configProvider.current() }
            ?: return chain.proceed(chain.request())

        val original = chain.request().url
        val existing = original.queryParameterNames
        val alreadySigned = SubsonicAuth.hasCredentials(existing)
        val builder = original.newBuilder()
        for ((name, value) in SubsonicAuth.params(config, clientName, json = true)) {
            if (name in existing) continue
            if (alreadySigned && name in SubsonicAuth.CREDENTIAL_PARAMS) continue
            builder.addQueryParameter(name, value)
        }
        val url = builder.build()

        val request = chain.request().newBuilder()
            .url(url)
            .build()

        val response = chain.proceed(request)
        val path = url.encodedPath
        if (response.isSuccessful) {
            Log.d(TAG, "$path → ${response.code}")
        } else {
            Log.e(TAG, "$path failed: ${response.code} ${response.message}")
        }
        return response
    }

    private companion object {
        const val TAG = "SubsonicAuth"
    }
}
