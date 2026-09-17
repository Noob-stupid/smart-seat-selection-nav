package site.zhinengzuo.seatnav;

import android.content.Intent;
import android.os.Bundle;
import android.webkit.WebView;

import com.getcapacitor.BridgeActivity;

/**
 * 主 Activity。
 *
 * 在 Capacitor 默认行为之上，增加「桌面快捷方式跳转」支持：
 * 长按 App 图标选「找空座 / 扫码占座 / 我的预约 / 语音选座」时，
 * 快捷方式会带 path（及可选 autoScan / autoVoice）启动本页，
 * 这里读出参数并让 WebView 跳到对应页面，同时注入一次性动作
 * window.__SHORTCUT__，由前端 native-features.js 读取后自动触发。
 */
public class MainActivity extends BridgeActivity {

    private String pendingPath = null;
    private String pendingAction = null;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        handleShortcut(getIntent());
        // ★ 冷启动也必须执行！
        //   旧代码只在 onNewIntent() 里调 applyPending()，于是从桌面快捷方式
        //   冷启动 App 时，path 永远不生效 —— 表现就是「跳到首页然后无事发生」。
        applyPending(true);
    }

    @Override
    public void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        pendingPath = null;
        pendingAction = null;
        handleShortcut(intent);
        applyPending(false);
    }

    /** 从 Intent 取快捷方式参数 */
    private void handleShortcut(Intent intent) {
        if (intent == null) return;
        String path = intent.getStringExtra("path");
        if (path != null && !path.isEmpty()) {
            pendingPath = path;
        }
        if ("1".equals(intent.getStringExtra("autoScan"))) pendingAction = "scan";
        if ("1".equals(intent.getStringExtra("autoVoice"))) pendingAction = "voice";
    }

    /**
     * 把待执行动作交给网页。
     *
     * 动作以 URL 参数形式传递（?autoscan=1 / ?autovoice=1），不再用
     * evaluateJavascript 注入 window.__SHORTCUT__ —— 后者在页面跳转后
     * 会被新文档冲掉，时序很难稳定。URL 参数跟着页面走，永远不丢。
     *
     * @param coldStart true = App 冷启动（要等 WebView 首次加载让位）
     */
    private void applyPending(boolean coldStart) {
        if (bridge == null) return;
        final WebView webView = bridge.getWebView();
        if (webView == null) return;

        String base = bridge.getServerUrl();
        if (base == null) base = "";
        base = base.replaceAll("/+$", "");

        String path = pendingPath;
        if (path == null && pendingAction != null) {
            // 只给了动作没给页面：给个合理的落脚页
            path = "scan".equals(pendingAction) ? "/reservation.html" : "/index.html";
        }

        if (path != null) {
            if (pendingAction != null) {
                path += (path.indexOf('?') >= 0 ? "&" : "?")
                        + ("scan".equals(pendingAction) ? "autoscan=1" : "autovoice=1");
            }
            final String target = base + path;
            webView.postDelayed(new Runnable() {
                @Override
                public void run() {
                    webView.loadUrl(target);
                }
            }, coldStart ? 700 : 0);
        }

        pendingPath = null;
        pendingAction = null;
    }
}
