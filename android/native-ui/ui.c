/* UI-only adapter for the existing module's two AddText branding callbacks.
 * No game state, input routing, license state, loading or module features are modified.
 * It uses the module's existing draw API, image callback and monotonic-clock import.
 */
typedef unsigned long uptr;
typedef unsigned int u32;
typedef struct { float x, y; } Vec2;
typedef struct { float x0, y0, x1, y1; } Rect;
typedef struct { long sec, nsec; } Timespec;
typedef struct { double started, seen; unsigned frames, drawing; } State;
typedef uptr (*GetArg)(void *, int);
typedef void (*SetArg)(void *, int, const void *);
typedef uptr (*GetCaller)(void *);
typedef float (*GetSize)(void *);
typedef Vec2 (*Measure)(void *, float, float, float, const char *, const char *, const char **);
typedef void (*DrawText)(void *, void *, float, const Vec2 *, u32, const char *, const char *, float, const Rect *);
typedef int (*Clock)(int, Timespec *);
extern void old_full(void *);
extern void old_plain(void *);
static const char label[] = "Melka DLC";
static const char empty[] = "";

static unsigned lower(unsigned c) { return c >= 'A' && c <= 'Z' ? c + 32 : c; }
static int contains(const char *s, const char *end, const char *term) {
    if (!s || (end && end < s)) return 0;
    for (unsigned i = 0; i < 128 && (!end || s+i < end) && s[i]; ++i) {
        unsigned j = 0;
        while (term[j] && i+j < 128 && (!end || s+i+j < end) && s[i+j] &&
               lower((unsigned char)s[i+j]) == lower((unsigned char)term[j])) ++j;
        if (!term[j]) return 1;
    }
    return 0;
}

int melka_link_label(const char *s, const char *end) {
    return contains(s,end,"zenin.cc") || contains(s,end,"telegram") || contains(s,end,"t.me/") ||
           contains(s,end,"@MelkaDLCRealese") || contains(s,end,"@crack_komarq");
}

static float ease(float x) { return x*x*(3.0f-2.0f*x); }
float melka_phase(double seconds) {
    if (seconds < 0.18 || seconds >= 1.84) return 0;
    if (seconds < 0.90) return ease((float)((seconds-0.18)/0.72));
    if (seconds < 1.12) return 1;
    return 1.0f-ease((float)((seconds-1.12)/0.72));
}

void melka_ui(void *ctx, uptr base, unsigned plain) {
    uptr *api = (uptr *)(base+0x7a99c50);
    GetArg get = (GetArg)api[0];
    SetArg set = (SetArg)api[1];
    GetCaller caller = (GetCaller)api[2];
    GetSize getsize = (GetSize)api[3];
    State *state = (State *)(base+0x7a9a000);
    if (!get || !set || !caller) return;
    unsigned textarg = plain ? 3 : 4;
    const char *text = (const char *)get(ctx,textarg);
    const char *end = (const char *)get(ctx,textarg+1);
    if (melka_link_label(text,end)) { set(ctx,textarg,empty); set(ctx,textarg+1,empty); return; }
    if (state->drawing) return;
    uptr site = caller(ctx)-base;
    int loading = plain ? site==0x577f4c : site==0x577ef8;
    if (!loading) { if(plain)old_plain(ctx);else old_full(ctx);return; }

    void *draw = (void *)get(ctx,0);
    const Vec2 *position = (const Vec2 *)get(ctx,plain?1:2);
    u32 color = (u32)get(ctx,plain?2:3);
    if (!draw || !position || !text) return;
    void *font;
    float size;
    if (plain) {
        unsigned char *shared = *(unsigned char **)((char *)draw+0x38);
        if(!shared)return;
        font=*(void **)(shared+0x18);
        size=*(float *)(shared+0x20);
    } else { font=(void *)get(ctx,1);size=getsize?getsize(ctx):0; }
    if(!font || !(size>0.0f && size<1024.0f))return;

    Timespec ts={0,0};
    Clock clock=(Clock)(base+0x680450); /* Existing clock_gettime PLT, preserves normal binding ABI. */
    double now;
    if(clock(1,&ts)==0)now=(double)ts.sec+(double)ts.nsec/1000000000.0;
    else now=(double)(++state->frames)/60.0;
    if(state->seen==0 || now<state->seen || now-state->seen>0.5)state->started=now;
    state->seen=now;
    float phase=melka_phase(now-state->started);
    Measure measure=(Measure)(base+0x5c8680);
    Vec2 original=measure(font,size,3.402823466e38f,0,text,end,(const char **)0);
    Vec2 word=measure(font,size,3.402823466e38f,0,label,label+9,(const char **)0);
    float gap=size*0.22f;
    float shift=(word.x+gap)*phase*0.5f;
    Vec2 moved={position->x-shift,position->y};
    Vec2 saved=*position;
    set(ctx,plain?1:2,&moved);
    if(plain)old_plain(ctx);else old_full(ctx);
    set(ctx,plain?1:2,position); /* Never leave a pointer into this stack in the captured context. */
    if(phase<=0.0001f)return;
    Vec2 at={saved.x+original.x*0.5f-shift+size*0.85f+gap,
             saved.y+original.y*0.5f-word.y*0.5f};
    Rect clip={at.x,at.y-2,at.x+word.x*phase,at.y+word.y+2};
    DrawText add=(DrawText)(base+0x7a7fa50); /* Existing full AddText trampoline, not the intercepted entry. */
    state->drawing=1;
    add(draw,font,size,&at,color,label,label+9,0,&clip);
    state->drawing=0;
}
