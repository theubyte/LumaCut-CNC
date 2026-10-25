plugins {
    id("com.android.application")
    kotlin("android")
    kotlin("plugin.compose")
    kotlin("plugin.serialization")
}

android {
    namespace = "de.millione.lumacut.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "de.millione.lumacut"
        minSdk = 26
        targetSdk = 35
        versionCode = (System.getenv("LUMACUT_VERSION_CODE") ?: "1").toInt()
        versionName = "1.0." + (System.getenv("LUMACUT_VERSION_CODE") ?: "0")
    }

    signingConfigs {
        create("release") {
            // Filled by CI from repository secrets; see .github/workflows/android.yml.
            val store = System.getenv("LUMACUT_KEYSTORE")
            if (store != null) {
                storeFile = file(store)
                storePassword = System.getenv("LUMACUT_KEYSTORE_PASSWORD")
                keyAlias = "lumacut"
                keyPassword = System.getenv("LUMACUT_KEYSTORE_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("release")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true }
    packaging { resources { excludes += setOf("/META-INF/{AL2.0,LGPL2.1}", "META-INF/versions/9/OSGI-INF/MANIFEST.MF") } }
}

dependencies {
    implementation(project(":core"))
    val bom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(bom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
}
