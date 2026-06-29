plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.yourcompany.usi_sm_os_app_v1"
    compileSdk = 36

    packaging {
        resources {
            // 排除重複的 INDEX.LIST 檔案
            excludes += "/META-INF/INDEX.LIST"

            // 如果後續還有報其他 META-INF 衝突，可以考慮加入以下幾行常用排除
            excludes += "/META-INF/io.netty.versions.properties"
            excludes += "/META-INF/OKIO.kotlin_module"
        }
    }

    defaultConfig {
        applicationId = "com.yourcompany.usi_sm_os_app_v1"
        minSdk = 33
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    kotlinOptions {
        jvmTarget = "11"
    }
}

dependencies {
        val ktor_version = "2.3.10"
        implementation("io.ktor:ktor-server-netty:$ktor_version")
        implementation("io.ktor:ktor-server-core:$ktor_version")
        implementation("io.ktor:ktor-server-content-negotiation:$ktor_version")
        implementation("io.ktor:ktor-serialization-gson:$ktor_version")
        // UI 與系統組件
        implementation("androidx.core:core-ktx:1.12.0")
        implementation("androidx.appcompat:appcompat:1.6.1")
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.material)
    implementation(libs.androidx.activity)
    implementation(libs.androidx.constraintlayout)
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
}