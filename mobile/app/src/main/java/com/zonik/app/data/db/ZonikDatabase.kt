package com.zonik.app.data.db

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(
    entities = [
        ArtistEntity::class,
        AlbumEntity::class,
        TrackEntity::class,
        PendingScrobbleEntity::class
    ],
    version = 4,
    exportSchema = false
)
abstract class ZonikDatabase : RoomDatabase() {

    abstract fun artistDao(): ArtistDao
    abstract fun albumDao(): AlbumDao
    abstract fun trackDao(): TrackDao
    abstract fun scrobbleDao(): PendingScrobbleDao

    companion object {
        /**
         * Adds the server's date-added to tracks/albums. Migrate rather than fall
         * back to a destructive rebuild: offlineCached and markedForDeletion are
         * local-only and can't be recovered from the server. `created` backfills
         * on the next sync; until then the ordering falls back to rowid.
         */
        private val MIGRATION_3_4 = object : Migration(3, 4) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE tracks ADD COLUMN created TEXT")
                db.execSQL("ALTER TABLE albums ADD COLUMN created TEXT")
            }
        }

        fun create(context: Context): ZonikDatabase {
            return Room.databaseBuilder(
                context,
                ZonikDatabase::class.java,
                "zonik.db"
            ).addMigrations(MIGRATION_3_4)
                .fallbackToDestructiveMigration()
                .build()
        }
    }
}
