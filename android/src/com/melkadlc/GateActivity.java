package com.melkadlc;

import android.app.Activity;
import android.content.*;
import android.graphics.*;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.*;
import android.security.keystore.*;
import android.util.Base64;
import android.view.*;
import android.widget.*;
import org.json.JSONObject;
import java.io.*;
import java.net.URL;
import java.security.KeyStore;
import java.util.*;
import java.util.concurrent.*;
import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;
import javax.net.ssl.HttpsURLConnection;

/** Mandatory server licensing. No root/process-loading implementation is changed. */
public final class GateActivity extends Activity {
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private LinearLayout content;
    private TextView status;
    private EditText key;
    private volatile boolean busy;
    private static volatile LicenseLease lease;
    private Button enterButton;
    private static final String BOT = "https://t.me/MelkaDLCtrialbot";
    private static final String CHANNEL = "https://t.me/MelkaDLCRealese";
    private static final String VERSION = "0.16-menu";
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final int BG = 0xff050505, CARD = 0xff151515;

    private static String api(Context c) throws Exception {
        InputStream in = c.getAssets().open("melkadlc.json");
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] b = new byte[2048]; int n;
        while ((n = in.read(b)) > 0) out.write(b,0,n);
        in.close();
        JSONObject config = new JSONObject(out.toString("UTF-8"));
        String base = config.getString("api_url");
        URL origin = new URL(base);
        if (!config.getBoolean("licensing_enabled") || !"https".equals(origin.getProtocol()) ||
                origin.getHost().isEmpty() || origin.getUserInfo()!=null || origin.getQuery()!=null ||
                origin.getRef()!=null || (!origin.getPath().isEmpty() && !"/".equals(origin.getPath())))
            throw new SecurityException("HTTPS required");
        return base;
    }

    public static boolean allowed(Context c) {
        try {
            api(c);
            LicenseLease current = lease;
            return current != null && current.valid(SystemClock.elapsedRealtime());
        } catch (Exception e) { return false; }
    }

    /** Called by the original Activity before its UI starts. */
    public static boolean require(final Activity a) {
        if (!allowed(a)) {
            a.startActivity(new Intent(a,GateActivity.class));
            a.finish();
            return false;
        }
        final Runnable[] poll = new Runnable[1];
        final long[] nextCheck = {SystemClock.elapsedRealtime()+20000};
        final java.util.concurrent.atomic.AtomicBoolean checking = new java.util.concurrent.atomic.AtomicBoolean(false);
        poll[0] = new Runnable() { public void run() {
            if (a.isFinishing() || a.isDestroyed()) return;
            if (!allowed(a)) {
                a.startActivity(new Intent(a,GateActivity.class)); a.finish(); return;
            }
            if(SystemClock.elapsedRealtime() >= nextCheck[0] && checking.compareAndSet(false,true)) {
            nextCheck[0]=SystemClock.elapsedRealtime()+20000;
            new Thread(new Runnable() { public void run() {
                try {
                    long started=SystemClock.elapsedRealtime();
                    JSONObject r = request(a,"GET","/v1/license",null,loadToken(a));
                    if(!a.isFinishing() && !a.isDestroyed()) accept(r,started);
                } catch(Exception e) {
                    lease=null;
                    MAIN.post(new Runnable() { public void run() {
                        if (!a.isFinishing()) { a.startActivity(new Intent(a,GateActivity.class)); a.finish(); }
                    }});
                } finally {checking.set(false);}
            }},"melka-license-check").start();
            }
            MAIN.postDelayed(poll[0],1000);
        }};
        MAIN.postDelayed(poll[0],1000);
        return true;
    }

    /** Add account information and links around the original root view without replacing its controls. */
    public static void decorate(final Activity a) {
        ViewGroup slot=(ViewGroup)a.findViewById(android.R.id.content);
        if(slot.getChildCount()!=1)return;
        View original=slot.getChildAt(0);slot.removeView(original);
        LinearLayout frame=new LinearLayout(a);frame.setOrientation(1);frame.setBackgroundColor(BG);
        final TextView badge=new TextView(a);badge.setTextColor(Color.WHITE);badge.setTextSize(12);
        badge.setGravity(Gravity.CENTER);badge.setPadding(12,10,12,10);
        frame.addView(badge,new LinearLayout.LayoutParams(-1,-2));
        frame.addView(original,new LinearLayout.LayoutParams(-1,0,1));
        LinearLayout links=new LinearLayout(a);
        String[] names={"ОБНОВЛЕНИЯ","ОТЧЁТ","КАНАЛ"};
        for(int index=0;index<names.length;index++) {
            final int action=index;
            Button b=new Button(a);b.setText(names[index]);b.setTextSize(10);b.setAllCaps(false);
            b.setTextColor(Color.WHITE);b.setBackgroundColor(CARD);
            links.addView(b,new LinearLayout.LayoutParams(0,-2,1));
            b.setOnClickListener(new View.OnClickListener(){public void onClick(View v){
                if(action==0)updates(a);
                if(action==1){Intent share=new Intent(Intent.ACTION_SEND);share.setType("text/plain");
                    share.putExtra(Intent.EXTRA_SUBJECT,"MELKADLC • DIAGNOSTICS");
                    share.putExtra(Intent.EXTRA_TEXT,"MELKADLC "+VERSION+"\nLicense verification: "+(allowed(a)?"ready":"required")+
                        "\nAndroid API: "+Build.VERSION.SDK_INT);
                    a.startActivity(Intent.createChooser(share,"ОТПРАВИТЬ ОТЧЁТ"));}
                if(action==2)browse(a,CHANNEL);
            }});
        }
        frame.addView(links);a.setContentView(frame);
        badge.setOnClickListener(new View.OnClickListener(){public void onClick(View v){browse(a,BOT);}});
        final Runnable[] tick=new Runnable[1];tick[0]=new Runnable(){public void run(){
            if(a.isFinishing()||a.isDestroyed())return;
            try {
                LicenseLease current=lease;
                long seconds=current==null?0:current.secondsLeft(SystemClock.elapsedRealtime());
                badge.setText("MELKADLC PREMIUM • "+(seconds>0?"ACTIVE":"EXPIRED")+"\n"+
                    String.format(Locale.ROOT,"Осталось: %d ч %02d мин • ПРОДЛИТЬ",seconds/3600,(seconds%3600)/60));
                MAIN.postDelayed(tick[0],1000);
            }catch(Exception e){badge.setText("MELKADLC • Проверьте подписку");}
        }};tick[0].run();
    }

    private static void browse(Activity a,String url){
        try{a.startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(url)));}
        catch(ActivityNotFoundException e){Toast.makeText(a,"Установите браузер или Telegram",Toast.LENGTH_SHORT).show();}
    }

    private static void updates(final Activity a){
        new Thread(new Runnable(){public void run(){
            String latest="—",notes="";
            try{JSONObject r=request(a,"GET","/v1/updates",null,null);latest=r.optString("latest_version","Не настроена");
                notes=r.optString("notes","");}catch(Exception ignored){}
            final String text="Текущая версия: "+VERSION+"\nПоследняя версия: "+latest+"\n"+notes;
            a.runOnUiThread(new Runnable(){public void run(){if(!a.isFinishing())
                new android.app.AlertDialog.Builder(a).setTitle("ОБНОВЛЕНИЯ MELKADLC").setMessage(text)
                    .setPositiveButton("КАНАЛ MELKADLC",new DialogInterface.OnClickListener(){public void onClick(DialogInterface d,int w){browse(a,CHANNEL);}})
                    .setNegativeButton("ЗАКРЫТЬ",null).show();}});
        }},"melka-updates").start();
    }

    @Override public void onCreate(Bundle bundle) {
        super.onCreate(bundle);
        getWindow().setStatusBarColor(BG); getWindow().setNavigationBarColor(BG);
        content = new LinearLayout(this); content.setOrientation(1); content.setGravity(Gravity.CENTER);
        content.setPadding(dp(28),dp(24),dp(28),dp(24)); content.setBackgroundColor(BG);
        content.addView(new Mark(this),new LinearLayout.LayoutParams(dp(132),dp(132)));
        content.addView(text("MELKADLC",30,Color.WHITE));
        content.addView(text("P R E M I U M   E X P E R I E N C E",10,0xffa0a0a0));
        ProgressBar progress = new ProgressBar(this);
        content.addView(progress,new LinearLayout.LayoutParams(dp(32),dp(32)));
        setContentView(content);
        // Splash waits for genuine certificate and component checks, never a timed delay.
        io.execute(new Runnable() { public void run() {
            try {
                Class.forName("a.b").getMethod("c",Context.class).invoke(null,GateActivity.this);
                api(GateActivity.this);
                runOnUiThread(new Runnable() { public void run() {
                    if(!isFinishing() && !isDestroyed()) {login(); verify();}
                }});
            } catch(Exception e) {
                runOnUiThread(new Runnable() { public void run() {
                    content.removeViewAt(content.getChildCount()-1);
                    content.addView(text("Ошибка проверки MELKADLC. Переустановите официальный APK.",14,Color.WHITE));
                }});
            }
        }});
    }

    private void login() {
        enterButton=null;
        content.removeAllViews();
        if(content.getParent() instanceof ViewGroup)((ViewGroup)content.getParent()).removeView(content);
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true);
        scroll.setBackgroundColor(BG); scroll.addView(content); setContentView(scroll);
        content.addView(new Mark(this),new LinearLayout.LayoutParams(dp(96),dp(96)));
        content.addView(text("WELCOME TO MELKADLC",23,Color.WHITE));
        content.addView(text("Добро пожаловать в MELKADLC.\nДля продолжения введите действующий лицензионный ключ.",14,0xffa0a0a0));
        key = new EditText(this); key.setSingleLine(true); key.setTextColor(Color.WHITE);
        key.setHintTextColor(0xff808080); key.setHint("MELKA-XXXX-XXXX-XXXX");
        key.setInputType(android.text.InputType.TYPE_CLASS_TEXT|android.text.InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS);
        key.setPadding(dp(18),dp(16),dp(18),dp(16)); key.setBackground(card(true));
        LinearLayout.LayoutParams field = new LinearLayout.LayoutParams(-1,-2); field.setMargins(0,dp(24),0,dp(12));
        content.addView(key,field);
        button("АКТИВИРОВАТЬ КЛЮЧ",new Runnable(){public void run(){activate();}},true);
        button("ПОЛУЧИТЬ КЛЮЧ В TELEGRAM",new Runnable(){public void run(){open(BOT);}},false);
        button("ПРОВЕРИТЬ ПОДПИСКУ",new Runnable(){public void run(){verify();}},false);
        button("ПОДДЕРЖКА",new Runnable(){public void run(){open(BOT);}},false);
        button("КАНАЛ @MelkaDLCRealese",new Runnable(){public void run(){open(CHANNEL);}},false);
        status=text("",14,0xffa0a0a0); content.addView(status);
    }

    private void activate() {
        if (busy) return;
        final String value=key.getText().toString().trim().toUpperCase(Locale.ROOT);
        if (!value.matches("MELKA-[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}")) {
            status.setText("Проверьте формат ключа."); return;
        }
        busy=true; status.setText("Проверка лицензии…");
        io.execute(new Runnable(){public void run(){
            try {
                SharedPreferences prefs=getSharedPreferences("melka-install",MODE_PRIVATE);
                String id=prefs.getString("id",null);
                if(id==null){id=UUID.randomUUID().toString();prefs.edit().putString("id",id).commit();}
                JSONObject body=new JSONObject().put("key",value).put("device_id",id);
                long started=SystemClock.elapsedRealtime();
                final JSONObject result=request(GateActivity.this,"POST","/v1/activate",body,null);
                accept(result,started); saveToken(GateActivity.this,result.getString("session_token"));
                success(result);
            } catch(final Exception e){error(e);} finally{busy=false;}
        }});
    }

    private void verify() {
        if(busy)return;
        busy=true; if(status!=null)status.setText("Проверка подписки…");
        io.execute(new Runnable(){public void run(){
            try {
                long started=SystemClock.elapsedRealtime();
                final JSONObject result=request(GateActivity.this,"GET","/v1/license",null,loadToken(GateActivity.this));
                accept(result,started); success(result);
            } catch(final Exception e){error(e);} finally{busy=false;}
        }});
    }

    private static void accept(JSONObject result,long started) throws Exception {
        LicenseLease next=new LicenseLease(result.getString("status"),result.getString("server_time"),
            result.getString("activated_at"),result.getString("expires_at"),started);
        if(!next.valid(SystemClock.elapsedRealtime()))throw new IOException("key_expired");
        lease=next;
    }

    private void success(final JSONObject result) {
        runOnUiThread(new Runnable(){public void run(){
            if(isFinishing() || isDestroyed())return;
            status.setText("ACCESS GRANTED\nMELKADLC PREMIUM • ACTIVE\nИстекает: "+result.optString("expires_at"));
            status.setAlpha(0); status.animate().alpha(1).setDuration(250).start();
            if(enterButton==null)enterButton=button("ОТКРЫТЬ MELKADLC",new Runnable(){public void run(){enter();}},true);
            enterButton.setEnabled(true);
        }});
    }

    private void error(final Exception e){lease=null;runOnUiThread(new Runnable(){public void run(){
        if(isFinishing() || isDestroyed())return;
        if(enterButton!=null)enterButton.setEnabled(false);
        String code=e.getMessage(),message="Ошибка подключения. Повторите проверку.";
        if("key_not_found".equals(code))message="Ключ не найден.";
        if("key_blocked".equals(code)||"account_blocked".equals(code))message="Доступ заблокирован.";
        if("key_expired".equals(code))message="Срок действия закончился. Продлите подписку в Telegram.";
        if("device_limit_reached".equals(code))message="DEVICE LIMIT REACHED\nЭтот ключ уже используется на другом устройстве.";
        if("session_invalid".equals(code))message="Введите лицензионный ключ для активации.";
        if("rate_limited".equals(code))message="Слишком много попыток. Повторите через минуту.";
        if(status!=null)status.setText(message);
    }});}

    private static JSONObject request(Context c,String method,String path,JSONObject body,String token) throws Exception {
        String base=api(c); if(base.isEmpty())throw new IOException("unconfigured");
        HttpsURLConnection con=(HttpsURLConnection)new URL(base+path).openConnection();
        con.setConnectTimeout(12000);con.setReadTimeout(12000);con.setRequestMethod(method);
        con.setInstanceFollowRedirects(false);
        if(token!=null)con.setRequestProperty("Authorization","Bearer "+token);
        try {
            if(body!=null){con.setDoOutput(true);con.setRequestProperty("Content-Type","application/json");
                OutputStream out=con.getOutputStream();out.write(body.toString().getBytes("UTF-8"));out.close();}
            int status=con.getResponseCode();
            InputStream in=status<400?con.getInputStream():con.getErrorStream();
            if(in==null)throw new IOException("connection");
            ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] b=new byte[2048];int n;
            while((n=in.read(b))>0){out.write(b,0,n);if(out.size()>32768)throw new IOException("response_limit");}
            in.close();JSONObject result=new JSONObject(out.toString("UTF-8"));
            if(status>=400)throw new IOException(result.optString("error","connection"));return result;
        } finally{con.disconnect();}
    }

    private static javax.crypto.SecretKey secret() throws Exception {
        KeyStore store=KeyStore.getInstance("AndroidKeyStore");store.load(null);
        if(store.containsAlias("melkadlc-session"))return (javax.crypto.SecretKey)store.getKey("melkadlc-session",null);
        KeyGenerator gen=KeyGenerator.getInstance("AES","AndroidKeyStore");
        gen.init(new KeyGenParameterSpec.Builder("melkadlc-session",KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
        return gen.generateKey();
    }

    private static void saveToken(Context c,String token)throws Exception{
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,secret());
        c.getSharedPreferences("melka-session",MODE_PRIVATE).edit()
            .putString("iv",Base64.encodeToString(cipher.getIV(),Base64.NO_WRAP))
            .putString("token",Base64.encodeToString(cipher.doFinal(token.getBytes("UTF-8")),Base64.NO_WRAP)).commit();
    }
    private static String loadToken(Context c)throws Exception{
        SharedPreferences p=c.getSharedPreferences("melka-session",MODE_PRIVATE);
        String value=p.getString("token",null);if(value==null)throw new IOException("session_invalid");
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,secret(),
            new GCMParameterSpec(128,Base64.decode(p.getString("iv",""),Base64.NO_WRAP)));
        return new String(cipher.doFinal(Base64.decode(value,Base64.NO_WRAP)),"UTF-8");
    }

    private int dp(int value){return (int)(getResources().getDisplayMetrics().density*value+.5f);}
    private TextView text(String value,int size,int color){TextView t=new TextView(this);t.setText(value);
        t.setTextSize(size);t.setTextColor(color);t.setGravity(Gravity.CENTER);t.setPadding(0,dp(10),0,dp(10));return t;}
    private GradientDrawable card(boolean stroke){GradientDrawable d=new GradientDrawable();d.setColor(CARD);
        d.setCornerRadius(dp(18));if(stroke)d.setStroke(dp(1),0x55ffffff);return d;}
    private Button button(String value,final Runnable action,boolean primary){
        Button b=new Button(this);b.setText(value);b.setTextSize(12);b.setAllCaps(false);
        b.setTextColor(primary?Color.BLACK:Color.WHITE);GradientDrawable d=card(true);
        if(primary)d.setColor(Color.WHITE);b.setBackground(d);
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,dp(54));p.setMargins(0,dp(8),0,0);
        content.addView(b,p);b.setOnClickListener(new View.OnClickListener(){public void onClick(View v){action.run();}});
        return b;
    }
    private void open(String url){try{startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(url)));}
        catch(ActivityNotFoundException e){if(status!=null)status.setText("Установите браузер или Telegram.");}}
    private void enter(){if(!allowed(this)){lease=null;verify();return;}try{Intent i=new Intent();i.setClassName(this,"com.local.moduleloader.MainActivity");
        startActivity(i);finish();}catch(Exception e){if(status!=null)status.setText("Не удалось открыть MELKADLC.");}}
    @Override public void onDestroy(){io.shutdownNow();super.onDestroy();}

    private static final class Mark extends View {
        private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
        Mark(Context c){super(c);setLayerType(View.LAYER_TYPE_SOFTWARE,null);setContentDescription("MELKADLC M");
            setAlpha(0);animate().alpha(1).setDuration(400).start();}
        @Override protected void onDraw(Canvas c){super.onDraw(c);c.save();c.scale(getWidth()/108f,getHeight()/108f);
            Path p=new Path();p.moveTo(22,80);p.lineTo(22,28);p.lineTo(34,28);p.lineTo(54,55);
            p.lineTo(74,28);p.lineTo(86,28);p.lineTo(86,80);p.lineTo(72,80);p.lineTo(72,50);
            p.lineTo(54,73);p.lineTo(36,50);p.lineTo(36,80);p.close();
            paint.setShader(new LinearGradient(0,25,0,84,new int[]{Color.WHITE,0xff7c828a,Color.WHITE},null,Shader.TileMode.CLAMP));
            paint.setStyle(Paint.Style.FILL);paint.setShadowLayer(8,0,0,0x77ffffff);c.drawPath(p,paint);
            paint.clearShadowLayer();paint.setShader(null);paint.setColor(Color.WHITE);paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(.7f);c.drawPath(p,paint);c.restore();}
    }
}
