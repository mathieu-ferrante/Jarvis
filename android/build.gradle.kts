// AGP 9 compile Kotlin lui-même (« built-in Kotlin ») : pas de plugin kotlin-android.
plugins {
    id("com.android.application") version "9.4.1" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.4.21" apply false
}
