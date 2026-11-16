# Los métodos del puente JS (window.CreatorHubAndroid) se llaman por reflexión desde la WebView.
-keepclassmembers class app.creatorhub.web.PuenteJs {
    @android.webkit.JavascriptInterface <methods>;
}
-keepattributes JavascriptInterface
