package com.zonik.core.security

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import android.util.Log
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Encrypts the credentials the apps keep in DataStore (the server API key, the Last.fm
 * session key) with an AES-GCM key held in the Android Keystore, so a copy of the app's data
 * directory — a backup, a rooted read, an adb pull on a debuggable build — no longer yields a
 * working key.
 *
 * Stored values carry a version prefix. A value without it is plain text from before this
 * existed; [decrypt] returns it as is, and the repositories re-save it encrypted on first run.
 *
 * Failure is deliberately soft. If the Keystore refuses to work (some TV boxes have had broken
 * Keystore implementations), [encrypt] stores the value as before rather than leaving the user
 * unable to sign in. If a stored value cannot be decrypted — the Keystore key does not survive
 * a backup restored to another device — [decrypt] returns null and the app treats the user as
 * signed out, so they pair again rather than hitting auth errors.
 */
object CredentialCipher {

    private const val TAG = "CredentialCipher"
    private const val KEYSTORE = "AndroidKeyStore"
    private const val KEY_ALIAS = "zonik_credentials"
    private const val PREFIX = "enc1:"
    private const val TRANSFORMATION = "AES/GCM/NoPadding"
    private const val TAG_BITS = 128
    private const val IV_BYTES = 12

    fun isEncrypted(stored: String): Boolean = stored.startsWith(PREFIX)

    /** The value to store: encrypted, or — only if the Keystore fails — [plain] unchanged. */
    fun encrypt(plain: String): String = try {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val sealed = cipher.iv + cipher.doFinal(plain.toByteArray(Charsets.UTF_8))
        PREFIX + Base64.encodeToString(sealed, Base64.NO_WRAP)
    } catch (e: Exception) {
        Log.w(TAG, "Keystore encryption unavailable; storing unencrypted", e)
        plain
    }

    /** The original value, or null when an encrypted value can no longer be decrypted. */
    fun decrypt(stored: String): String? {
        if (!isEncrypted(stored)) return stored
        return try {
            val sealed = Base64.decode(stored.removePrefix(PREFIX), Base64.NO_WRAP)
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(
                Cipher.DECRYPT_MODE, key(),
                GCMParameterSpec(TAG_BITS, sealed, 0, IV_BYTES)
            )
            String(cipher.doFinal(sealed, IV_BYTES, sealed.size - IV_BYTES), Charsets.UTF_8)
        } catch (e: Exception) {
            Log.w(TAG, "Stored credential could not be decrypted; treating as signed out", e)
            null
        }
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance(KEYSTORE).apply { load(null) }
        (store.getEntry(KEY_ALIAS, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build()
        )
        return generator.generateKey()
    }
}
