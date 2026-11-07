package com.vjsamir.oscpad;

import android.app.Activity;
import android.content.Context;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Vibrator;
import android.view.View;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebChromeClient;
import android.content.Intent;
import java.util.HashSet;
import java.util.Set;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.NetworkInterface;
import java.nio.ByteBuffer;
import java.nio.charset.Charset;
import java.util.Collections;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {
    private WebView web;
    private final ExecutorService tx = Executors.newSingleThreadExecutor();
    private DatagramSocket sendSock;
    private volatile InetAddress target;
    private volatile int targetPort = 7000;
    private volatile int fbPort = -1;
    private Thread fbThread;
    private DatagramSocket fbSock;
    private Vibrator vib;
    private volatile Set<String> watched = new HashSet<String>();
    private volatile boolean learning = false;
    private volatile boolean auto = true;
    private volatile String bridgeName = "";
    private volatile String bridgeIp = "";
    private volatile long lastPong = 0;
    private volatile boolean resAlive = false;
    private Thread discThread;
    private static final java.util.regex.Pattern LEARN = java.util.regex.Pattern.compile("^/composition/layers/\\d+/clips/\\d+/(connected|select|selected)$");
    private static final Charset UTF8 = Charset.forName("UTF-8");

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        vib = (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);
        web = new WebView(this);
        WebSettings ws = web.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setAllowFileAccess(true);
        ws.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        ws.setCacheMode(WebSettings.LOAD_NO_CACHE);
        web.setWebViewClient(new WebViewClient());
        web.setWebChromeClient(new WebChromeClient());
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);
        web.setBackgroundColor(0xFF07070C);
        web.addJavascriptInterface(new Bridge(), "Android");
        setContentView(web);
        hideBars();
        web.loadUrl("file:///android_asset/index.html");
        startDiscovery();
    }

    private void hideBars() {
        web.setSystemUiVisibility(View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_FULLSCREEN
                | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN);
    }

    @Override
    public void onWindowFocusChanged(boolean f) { super.onWindowFocusChanged(f); if (f) hideBars(); }

    @Override
    protected void onDestroy() {
        stopFeedback();
        tx.shutdownNow();
        if (sendSock != null) sendSock.close();
        super.onDestroy();
    }

    // ---------------- auto discovery of PC bridge
    private void startDiscovery() {
        discThread = new Thread(new Runnable() { public void run() {
            DatagramSocket ds = null;
            try {
                ds = new DatagramSocket();
                ds.setBroadcast(true);
                ds.setSoTimeout(700);
                byte[] buf = new byte[512];
                while (!Thread.currentThread().isInterrupted()) {
                    if (auto) {
                        long now = System.currentTimeMillis();
                        if (now - lastPong > 6000) {
                            byte[] q = "VJPAD_DISCOVER".getBytes(UTF8);
                            try { ds.send(new DatagramPacket(q, q.length, InetAddress.getByName("255.255.255.255"), 7099)); } catch (Exception ignored) { }
                            String sb = subnetBroadcast();
                            if (sb != null) try { ds.send(new DatagramPacket(q, q.length, InetAddress.getByName(sb), 7099)); } catch (Exception ignored) { }
                            try {
                                DatagramPacket p = new DatagramPacket(buf, buf.length);
                                ds.receive(p);
                                String r = new String(p.getData(), 0, p.getLength(), UTF8);
                                if (r.startsWith("VJPAD_BRIDGE|")) {
                                    String[] parts = r.split("\\|");
                                    bridgeName = parts.length > 1 ? parts[1] : "PC";
                                    targetPort = parts.length > 2 ? Integer.parseInt(parts[2].trim()) : 7010;
                                    target = p.getAddress();
                                    bridgeIp = target.getHostAddress();
                                    lastPong = System.currentTimeMillis() - 3000;
                                }
                            } catch (Exception ignored) { }
                        }
                        if (target != null && !bridgeIp.isEmpty()) {
                            try {
                                JSONArray a = new JSONArray(); a.put(fbPort > 0 ? fbPort : 7001);
                                byte[] pkt = encode("/vjpad/ping", a);
                                if (sendSock == null) sendSock = new DatagramSocket();
                                sendSock.send(new DatagramPacket(pkt, pkt.length, target, targetPort));
                            } catch (Exception ignored) { }
                        }
                    }
                    try { Thread.sleep(1500); } catch (InterruptedException e) { break; }
                }
            } catch (Exception ignored) {
            } finally { if (ds != null) ds.close(); }
        }});
        discThread.setDaemon(true);
        discThread.start();
    }

    private String subnetBroadcast() {
        try {
            for (NetworkInterface ni : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!ni.isUp() || ni.isLoopback()) continue;
                for (java.net.InterfaceAddress ia : ni.getInterfaceAddresses())
                    if (ia.getAddress() instanceof Inet4Address && ia.getBroadcast() != null) return ia.getBroadcast().getHostAddress();
            }
        } catch (Exception ignored) { }
        return null;
    }

    // ---------------- OSC encoding
    private static void pad(ByteArrayOutputStream o) { while (o.size() % 4 != 0) o.write(0); }
    private static void str(ByteArrayOutputStream o, String s) {
        byte[] b = s.getBytes(UTF8); o.write(b, 0, b.length); o.write(0); pad(o);
    }
    static byte[] encode(String addr, JSONArray args) throws Exception {
        ByteArrayOutputStream o = new ByteArrayOutputStream();
        str(o, addr);
        StringBuilder tags = new StringBuilder(",");
        ByteArrayOutputStream data = new ByteArrayOutputStream();
        for (int i = 0; i < args.length(); i++) {
            Object a = args.get(i);
            if (a instanceof JSONObject && ((JSONObject) a).has("f")) {
                tags.append('f'); data.write(ByteBuffer.allocate(4).putFloat((float) ((JSONObject) a).getDouble("f")).array());
            } else if (a instanceof Integer || a instanceof Long || a instanceof Boolean) {
                int v = (a instanceof Boolean) ? (((Boolean) a) ? 1 : 0) : ((Number) a).intValue();
                tags.append('i'); data.write(ByteBuffer.allocate(4).putInt(v).array());
            } else if (a instanceof Number) {
                tags.append('f'); data.write(ByteBuffer.allocate(4).putFloat(((Number) a).floatValue()).array());
            } else {
                tags.append('s'); str(data, String.valueOf(a));
            }
        }
        str(o, tags.toString());
        byte[] d = data.toByteArray(); o.write(d, 0, d.length);
        return o.toByteArray();
    }

    // ---------------- OSC decoding (feedback)
    private static int strEnd(byte[] b, int i, int n) { int j = i; while (j < n && b[j] != 0) j++; return j; }
    private void parse(byte[] b, int off, int n) {
        try {
            if (n >= 8 && new String(b, off, 7, UTF8).equals("#bundle")) {
                int i = off + 16;
                while (i + 4 <= off + n) {
                    int len = ByteBuffer.wrap(b, i, 4).getInt(); i += 4;
                    parse(b, i, len); i += len;
                }
                return;
            }
            int end = off + n;
            int j = strEnd(b, off, end);
            String addr = new String(b, off, j - off, UTF8);
            if (addr.equals("/vjpad/pong")) {
                lastPong = System.currentTimeMillis();
                int ti = (j + 4 - off) / 4 * 4 + off; int tk = strEnd(b, ti, end);
                int vi = (tk + 4 - off) / 4 * 4 + off;
                if (tk - ti >= 2 && b[ti + 1] == 'i') resAlive = ByteBuffer.wrap(b, vi, 4).getInt() == 1;
                return;
            }
            boolean w = watched.contains(addr);
            if (!w && !learning) return;
            if (!w && (addr.contains("/transport/position") || addr.contains("/tempocontroller/") || addr.endsWith("/thumbnail"))) return;
            int i = (j + 4 - off) / 4 * 4 + off;
            int k = strEnd(b, i, end);
            String tags = new String(b, i, k - i, UTF8);
            i = (k + 4 - off) / 4 * 4 + off;
            JSONArray out = new JSONArray();
            for (int t = 1; t < tags.length(); t++) {
                char c = tags.charAt(t);
                if (c == 'i') { out.put(ByteBuffer.wrap(b, i, 4).getInt()); i += 4; }
                else if (c == 'f') { out.put((double) ByteBuffer.wrap(b, i, 4).getFloat()); i += 4; }
                else if (c == 's') { int e = strEnd(b, i, end); out.put(new String(b, i, e - i, UTF8)); i = (e + 4 - off) / 4 * 4 + off; }
                else if (c == 'd' || c == 'h') { i += 8; }
            }
            final String js = "window.__fb(" + JSONObject.quote(addr) + "," + out.toString() + "," + JSONObject.quote(tags.length() > 1 ? tags.substring(1) : "") + ")";
            web.post(new Runnable() { public void run() { web.evaluateJavascript(js, null); } });
        } catch (Exception ignored) { }
    }

    private synchronized void startFeedback(final int port) {
        if (port == fbPort && fbThread != null) return;
        stopFeedback();
        fbPort = port;
        fbThread = new Thread(new Runnable() {
            public void run() {
                WifiManager.MulticastLock lock = null;
                try {
                    fbSock = new DatagramSocket(null);
                    fbSock.setReuseAddress(true);
                    fbSock.bind(new InetSocketAddress(port));
                    byte[] buf = new byte[65535];
                    while (!Thread.currentThread().isInterrupted()) {
                        DatagramPacket p = new DatagramPacket(buf, buf.length);
                        fbSock.receive(p);
                        parse(p.getData(), 0, p.getLength());
                    }
                } catch (Exception ignored) {
                }
            }
        });
        fbThread.setDaemon(true);
        fbThread.start();
    }

    private synchronized void stopFeedback() {
        if (fbThread != null) fbThread.interrupt();
        if (fbSock != null) fbSock.close();
        fbThread = null; fbSock = null;
    }

    // ---------------- JS bridge
    class Bridge {
        @JavascriptInterface
        public void config(final String ip, final int port, final int feedbackPort) {
            auto = false; bridgeIp = "";
            targetPort = port;
            tx.execute(new Runnable() { public void run() {
                try { target = InetAddress.getByName(ip.trim()); } catch (Exception e) { target = null; }
            }});
            startFeedback(feedbackPort);
        }

        @JavascriptInterface
        public void send(final String json) {
            tx.execute(new Runnable() { public void run() {
                try {
                    if (target == null) return;
                    if (sendSock == null) sendSock = new DatagramSocket();
                    JSONArray list = new JSONArray(json);
                    for (int i = 0; i < list.length(); i++) {
                        JSONArray m = list.getJSONArray(i);
                        byte[] pkt = encode(m.getString(0), m.getJSONArray(1));
                        sendSock.send(new DatagramPacket(pkt, pkt.length, target, targetPort));
                    }
                } catch (Exception ignored) { }
            }});
        }

        @JavascriptInterface
        public String myIp() {
            try {
                for (NetworkInterface ni : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                    if (!ni.isUp() || ni.isLoopback()) continue;
                    for (InetAddress a : Collections.list(ni.getInetAddresses()))
                        if (a instanceof Inet4Address) return a.getHostAddress();
                }
            } catch (Exception ignored) { }
            return "?";
        }

        @JavascriptInterface
        public void learn(boolean on) { learning = on; }

        @JavascriptInterface
        public void setAuto(boolean on, int feedbackPort) {
            auto = on;
            if (on) { target = null; bridgeIp = ""; lastPong = 0; }
            startFeedback(feedbackPort);
        }

        @JavascriptInterface
        public String status() {
            try {
                JSONObject o = new JSONObject();
                boolean con = auto ? (System.currentTimeMillis() - lastPong < 6000) : (target != null);
                o.put("auto", auto); o.put("connected", con); o.put("ip", auto ? bridgeIp : (target != null ? target.getHostAddress() : ""));
                o.put("name", bridgeName); o.put("res", auto ? resAlive : false);
                return o.toString();
            } catch (Exception e) { return "{}"; }
        }

        @JavascriptInterface
        public void watch(String json) {
            try {
                JSONArray a = new JSONArray(json);
                Set<String> s = new HashSet<String>();
                for (int i = 0; i < a.length(); i++) s.add(a.getString(i));
                watched = s;
            } catch (Exception ignored) { }
        }

        @JavascriptInterface
        public void share(final String text) {
            runOnUiThread(new Runnable() { public void run() {
                Intent i = new Intent(Intent.ACTION_SEND);
                i.setType("text/plain");
                i.putExtra(Intent.EXTRA_SUBJECT, "VJ OSC Pad layout");
                i.putExtra(Intent.EXTRA_TEXT, text);
                startActivity(Intent.createChooser(i, "Layout share karo"));
            }});
        }

        @JavascriptInterface
        public void vibrate() {
            try { if (vib != null) vib.vibrate(8); } catch (Exception ignored) { }
        }
    }
}
