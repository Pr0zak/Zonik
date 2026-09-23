package com.zonik.app.screenshots

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Shader
import android.graphics.drawable.BitmapDrawable
import coil.ImageLoader
import coil.decode.DataSource
import coil.intercept.Interceptor
import coil.request.ImageResult
import coil.request.SuccessResult
import com.zonik.core.model.Album
import com.zonik.core.model.Playlist
import com.zonik.core.model.Track

/** Made-up library used by the screenshot tests. */
object SampleData {
    private val artists = listOf(
        "Aurora Fields", "The Night Ferries", "Kaito Mori", "Velvet Static", "Lumen Drive",
        "Marisol Vega", "Cold Harbour", "Neon Pilgrims", "Juniper Lane", "Echo Canyon",
    )
    private val albums = listOf(
        "Paper Satellites", "Low Tide Radio", "Glass Orchard", "Midnight Transit", "Soft Machines",
        "Northern Lights", "Hollow Coast", "Signal & Noise", "Wild Blue Hour", "Afterglow",
    )
    private val titles = listOf(
        "Borrowed Sunlight", "Static Hearts", "Runaway Signal", "Tidal", "Honey & Smoke",
        "Parallel Lines", "Slow Burn", "Afterimage", "Neon Rain", "The Long Way Home",
        "Satellite Kids", "Glasshouse", "Cold Water", "Ember", "Weightless",
        "Night Swim", "Paper Crowns", "Wildfire", "Echoes", "Daybreak",
    )

    val tracks: List<Track> = titles.mapIndexed { i, title ->
        val a = i % artists.size
        Track(
            id = "t$i",
            title = title,
            artist = artists[a],
            artistId = "ar$a",
            album = albums[a],
            albumId = "al$a",
            coverArt = "al$a",
            duration = 150 + (i * 37) % 180,
            track = i % 12 + 1,
            year = 2008 + i % 16,
            genre = listOf("Indie", "Electronic", "Rock", "Synthpop")[i % 4],
            bitRate = listOf(320, 1011, 256)[i % 3],
            suffix = listOf("mp3", "flac", "m4a")[i % 3],
            starred = i % 5 == 0,
            playCount = (i * 7) % 40,
        )
    }

    val album = Album(
        id = "al0", name = albums[0], artist = artists[0], artistId = "ar0", coverArt = "al0",
        year = 2019, songCount = 11, duration = 2710, genre = "Indie",
    )
    val albumTracks = (0 until 11).map { i ->
        tracks[i].copy(id = "a$i", album = album.name, albumId = album.id, coverArt = album.coverArt,
            artist = album.artist, artistId = album.artistId, track = i + 1)
    }

    val playlists = listOf(
        Playlist("p1", "Morning Commute", songCount = 42, duration = 9800, coverArt = "al2"),
        Playlist("p2", "Deep Focus", songCount = 118, duration = 27400, coverArt = "al4"),
        Playlist("p3", "Road Trip 2026", songCount = 64, duration = 15100, coverArt = "al6"),
        Playlist("p4", "Late Night", songCount = 23, duration = 5200, coverArt = "al8"),
        Playlist("p5", "Gym", songCount = 37, duration = 7900, coverArt = "al1"),
        Playlist("p6", "AI: rainy sunday jazz", songCount = 25, duration = 6100, coverArt = null),
    )
}

/**
 * Stands in for the network: every image request gets a gradient derived from the URL,
 * so each "album" has its own stable cover.
 */
class FakeCoverInterceptor : Interceptor {
    override suspend fun intercept(chain: Interceptor.Chain): ImageResult {
        val key = chain.request.data.toString()
        val h = key.hashCode()
        val hue1 = (h and 0xFF) / 255f * 360f
        val c1 = android.graphics.Color.HSVToColor(floatArrayOf(hue1, 0.55f, 0.75f))
        val c2 = android.graphics.Color.HSVToColor(floatArrayOf((hue1 + 60f) % 360f, 0.7f, 0.35f))
        val bmp = Bitmap.createBitmap(200, 200, Bitmap.Config.ARGB_8888)
        Canvas(bmp).drawRect(0f, 0f, 200f, 200f, Paint().apply {
            shader = LinearGradient(0f, 0f, 200f, 200f, c1, c2, Shader.TileMode.CLAMP)
        })
        return SuccessResult(
            drawable = BitmapDrawable(chain.request.context.resources, bmp),
            request = chain.request,
            dataSource = DataSource.MEMORY,
        )
    }
}

fun fakeImageLoader(context: android.content.Context): ImageLoader =
    ImageLoader.Builder(context)
        .components { add(FakeCoverInterceptor()) }
        // Resolve on the calling thread so the image is there before Paparazzi draws.
        .dispatcher(kotlinx.coroutines.Dispatchers.Unconfined)
        // Paparazzi draws one frame, before an async load can land, so what shows is the
        // placeholder: a stand-in cover.
        .placeholder(
            android.graphics.drawable.GradientDrawable(
                android.graphics.drawable.GradientDrawable.Orientation.TL_BR,
                intArrayOf(0xFF8E6BD8.toInt(), 0xFF2B1F55.toInt())
            )
        )
        .crossfade(false)
        .build()
