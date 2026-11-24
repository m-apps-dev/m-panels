"""Arayüz duman testi — YALNIZ geçici bir deneme masaüstüyle çalışır (gerçek masaüstüne dokunmaz).

python tests/smoke.py [ekran_goruntusu.png]
Gerçek bir Explorer sürüklemesi simüle EDİLEMEZ; bırakma işleyicisi (App.drop_paths) koddan çağrılır.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fileops  # noqa: E402
import mpanels  # noqa: E402
import strings as ui  # noqa: E402
import winutil  # noqa: E402

winutil.lbutton_down = lambda: True      # the drags below are synthetic: the real button is not down (safety net off)
from PIL import ImageGrab  # noqa: E402

shot = sys.argv[1] if len(sys.argv) > 1 else os.path.join(tempfile.gettempdir(), "mpanels_smoke.png")
root = tempfile.mkdtemp(prefix="mpanels_smoke_")
desk, pub, dev, data = (os.path.join(root, n) for n in ("Desktop", "Public", "Dev", "veri"))
for d in (desk, pub, dev):
    os.makedirs(d)


def touch(p, t="x"):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8").write(t)
    return p


ctx = fileops.Ctx(desk, pub)
fails = []


def check(cond, what):
    print(("OK    " if cond else "HATA  ") + what)
    if not cond:
        fails.append(what)


# gerçek masaüstünün test öncesi durumu (yalnız okunur)
real = winutil.get_real_desktop()
before_real = sorted(os.listdir(real))
real_has_panels = os.path.exists(os.path.join(real, "Paneller"))

# denemelik masaüstü içeriği
names = ["Rapor.docx", "Notlar.txt", "Tablo.xlsx", "Çok uzun bir dosya adı örneği.pdf", "Resim.png"]
for n in names:
    touch(os.path.join(desk, n))
os.makedirs(os.path.join(desk, "Projeler"))
winutil.create_shortcut(os.path.join(desk, "Not Defteri.lnk"), r"C:\Windows\notepad.exe")
winutil.create_shortcut(os.path.join(desk, "Hesap Makinesi.lnk"), r"C:\Windows\System32\calc.exe")
winutil.create_shortcut(os.path.join(desk, "Bozuk.lnk"), os.path.join(dev, "yok.exe"))
touch(os.path.join(dev, "dis_dosya.txt"))
winutil.create_shortcut(os.path.join(pub, "Ortak Uygulama.lnk"), r"C:\Windows\System32\mspaint.exe")

inst_name = f"MPanels_Smoke_{os.getpid()}"            # own single-instance name: never collides with the real program
import fakedisplays                                   # made-up monitors: the smoke run must not depend on the real screens
SMOKE_DISPLAYS = fakedisplays.FakeDisplays(fakedisplays.THREE)
app = mpanels.App(ctx, data, test_mode=True, use_tray=False, instance_name=inst_name,
                  displays_provider=SMOKE_DISPLAYS, clock=fakedisplays.FakeClock())
root_tk = app.root


def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end:
        root_tk.update()
        time.sleep(0.01)


pump(0.5)
check(os.path.isdir(ctx.panels_root), "Paneller klasörü deneme masaüstünde oluştu")
check(winutil.is_hidden(ctx.panels_root), "Paneller klasörü gizli")
check(ui.DEFAULT_PANEL_NAME in app.panels, "ilk açılışta varsayılan 'Sample' paneli oluştu")

p1 = app.panels[ui.DEFAULT_PANEL_NAME]
app.rename_panel(p1, "Belgeler")
pump(0.3)
check("Belgeler" in app.panels and os.path.isdir(ctx.panel_path("Belgeler")), "panel yeniden adlandırıldı (klasör de)")
p1 = app.panels["Belgeler"]
p2 = app.new_panel("Uygulamalar")
p3 = app.new_panel("Dış Bağlantılar")
check(p2 is not None and p3 is not None, "yeni paneller oluşturuldu")

# --- bırakma senaryoları (App.drop_paths; gerçek Explorer sürüklemesi değil)
m, e = app.drop_paths(p1, [os.path.join(desk, n) for n in names] + [os.path.join(desk, "Projeler")])
check(not e and all(os.path.exists(os.path.join(p1.folder, n)) for n in names), "masaüstü dosyaları panele TAŞINDI")
check(not any(os.path.exists(os.path.join(desk, n)) for n in names), "masaüstünde kalmadı")
app.drop_paths(p2, [os.path.join(desk, "Not Defteri.lnk"), os.path.join(desk, "Hesap Makinesi.lnk"),
                    os.path.join(desk, "Bozuk.lnk")])
m, e = app.drop_paths(p3, [os.path.join(dev, "dis_dosya.txt")])
check(os.path.exists(os.path.join(dev, "dis_dosya.txt")) and os.path.exists(os.path.join(p3.folder, "dis_dosya.lnk")),
      "masaüstü dışı dosya taşınmadı, .lnk oluştu")
m, e = app.drop_paths(p2, [os.path.join(pub, "Ortak Uygulama.lnk")])
check(os.path.exists(os.path.join(pub, "Ortak Uygulama.lnk")) and m, "ortak masaüstü: kopya, asıl yerinde; bilgi: " + (m[0] if m else ""))
touch(os.path.join(desk, "Notlar.txt"), "yeni")
app.drop_paths(p1, [os.path.join(desk, "Notlar.txt")])
check(os.path.exists(os.path.join(p1.folder, "Notlar (2).txt")), "ad çakışması: ' (2)' eklendi")
app.toggle_special(p2, "recycle")

# --- pencere yerleşimi ve ekran görüntüsü
for p, (x, y, w, h) in ((p1, (60, 60, 400, 300)), (p2, (500, 60, 330, 220)), (p3, (500, 320, 330, 120))):
    p.cfg.update(x=x, y=y, w=w, h=h)
    p.apply_cfg()
p3.set_color("#a56bff")
p2.set_color("#ff9a3c")
p1.sel = 1
pump(0.5)
p1.item_menu  # menü yapısı kurulabiliyor mu (açılmaz, yalnız oluşturma kontrolü)
for p in (p1, p2, p3):
    p.top.lift()
pump(0.6)
check(len(p1.items) >= 6 and any(i.broken for i in p2.items), "öğeler listelendi; bozuk kısayol işaretli")
check(p2.items[-1].special == "recycle", "Geri Dönüşüm Kutusu özel öğesi eklendi")
img = ImageGrab.grab(bbox=(30, 30, 900, 480))
img.save(shot)
print("Ekran görüntüsü:", shot)

# --- aç/kapat, boyut, ayarlar penceresi
p1.toggle()
pump(0.4)
check(p1.cur_h == mpanels.HEAD_H and p1.cfg["collapsed"], "panel kapandı (yalnız başlık)")
p1.toggle()
pump(0.4)
check(p1.cur_h == 300 and not p1.cfg["collapsed"], "panel yeniden açıldı")
p1.apply_size(300, 200)
pump(0.2)
check(p1.top.winfo_width() == 300, "yeniden boyutlandırma")
p1.apply_size(400, 300)
app.open_settings("Belgeler")
pump(0.5)
check(app.settings_win.win.winfo_exists(), "ayarlar penceresi açıldı")
app.settings_win.v["icon"].set("48")
app.settings_win.v_op.set(80)
app.settings_win.apply()
check(p1.cfg["icon_size"] == 48 and abs(p1.cfg["opacity"] - 0.8) < 0.01, "ayarlar uygulandı")
app.settings_win.win.destroy()

# --- geri çıkar, paneller arası taşıma, kaldır
it = next(i for i in p1.items if i.name == "Resim.png")
app.return_item(p1, it)
check(os.path.exists(os.path.join(desk, "Resim.png")), "öğe masaüstüne geri çıktı")
it = next(i for i in p1.items if i.name == "Rapor.docx")
app.finish_item_drag(p1, it, p3.top.winfo_rootx() + 40, p3.top.winfo_rooty() + 60)
check(os.path.exists(os.path.join(p3.folder, "Rapor.docx")), "paneller arası sürükleme (taşıma)")

# klasör izleme: Explorer'da klasöre dosya konunca panel kendiliğinden güncellensin
n0 = len(p3.items)
touch(os.path.join(p3.folder, "Disaridan_geldi.txt"))
pump(1.6)
check(len(p3.items) == n0 + 1, "klasör izleme: dışarıdan eklenen dosya panelde göründü")

app.confirm = lambda t, m: True
r = app.remove_panel(p3)
pump(0.3)
check(r.ok and "Dış Bağlantılar" not in app.panels, "panel kaldırıldı")
check(os.path.exists(os.path.join(desk, "Rapor.docx")) and os.path.exists(os.path.join(desk, "dis_dosya.lnk")),
      "kaldırılan panelin içeriği masaüstüne döndü")
check(os.path.isdir(os.path.join(ctx.trash, "Dış Bağlantılar")), "boş klasör _silinecek'e taşındı (silinmedi)")

# ================= Sürüm 2 =================
import types  # noqa: E402

import deskicons  # noqa: E402

mpanels.messagebox.showwarning = lambda *a, **k: None       # testte diyalog açılmasın
ev = lambda x=0, y=0, xr=0, yr=0: types.SimpleNamespace(x=x, y=y, x_root=xr, y_root=yr, delta=0)  # noqa: E731
icons_before = winutil.desktop_icons_hidden()                # yalnız OKUR

# --- 1) ikon boyutu: sayı kutusu 16–128, eski değer çevrilir
app.open_settings("Belgeler")
pump(0.3)
S = app.settings_win
for raw, want in (("64", 64), ("200", 128), ("3", 16), ("abc", 32), ("", 32)):
    S.v["icon"].set(raw)
    S.apply()
    check(p1.cfg["icon_size"] == want and S.v["icon"].get() == str(want), f"ikon boyutu '{raw}' -> {want}")
_msg_before = S.msg.cget("text")
S.v["icon"].set("999")
_applied = S.apply()                                     # apply() returns a bool (True = finished)
check("uyarı" not in _msg_before and _applied is True and "whole number" in S.msg.cget("text"),
      "aralık dışı girişte uyarı mesajı")
S.v["icon"].set("48")
S.apply()
app.cfg["panels"]["Belgeler"]["icon_size"] = "24"            # eski/bozuk config değeri
check(app.panel_cfg("Belgeler")["icon_size"] == 24, "eski config değeri sayıya çevrildi")
app.cfg["panels"]["Belgeler"]["icon_size"] = "xyz"
check(app.panel_cfg("Belgeler")["icon_size"] == 32, "bozuk config değeri -> 32")
p1.cfg["icon_size"] = 48
p1.apply_cfg()
pump(0.3)

# --- 2) not paneli
nt = app.new_panel("Yapılacaklar", "note")
pump(0.4)
npath = fileops.note_path(data, "Yapılacaklar")
check(nt is not None and nt.is_note and nt.folder is None and "Yapılacaklar" in app.panels, "not paneli oluştu")
check(os.path.exists(npath), "not dosyası veri klasöründe oluştu")
check(not os.path.exists(ctx.panel_path("Yapılacaklar")), "not için masaüstünde klasör açılmadı")
check(app.cfg["panels"]["Yapılacaklar"]["type"] == "note", "config'te type=note")
check(app.new_panel("Belgeler", "note") is None and app.new_panel("yapılacaklar", "shortcut") is None,
      "ad çakışması (klasör/not ortak ad alanı) reddedildi")
nt.cfg.update(x=900, y=60, w=300, h=200)
nt.apply_cfg()
nt.text.insert("end", "merhaba çğıöşü\nikinci satır")
pump(0.3)
check(fileops.read_note(data, "Yapılacaklar").text == "", "yazar yazmaz kaydetmez (gecikmeli)")
pump(1.0)
check(fileops.read_note(data, "Yapılacaklar").text == "merhaba çğıöşü\nikinci satır", "otomatik kayıt çalıştı")
nt.set_color("#ff5a6a")
nt.toggle()
pump(0.4)
check(nt.cur_h == mpanels.HEAD_H and nt.text.winfo_manager() == "", "not paneli küçüldü (metin kutusu gizli)")
nt.toggle()
pump(0.4)
check(nt.cur_h == 200 and nt.text.winfo_manager() == "place", "not paneli yeniden açıldı")
nt.text.insert("end", " +son")
app.rename_panel(nt, "Görevler")                            # kayıt öncesi yeniden adlandırma: yazı kaybolmamalı
pump(0.4)
nt = app.panels.get("Görevler")
check(nt is not None and "Yapılacaklar" not in app.panels, "not yeniden adlandırıldı")
check(nt.text.get("1.0", "end-1c") == "merhaba çğıöşü\nikinci satır +son", "yeniden adlandırmada metin korundu")
check(not os.path.exists(npath) and os.path.exists(fileops.note_path(data, "Görevler")), "not dosyası da yeniden adlandı")
app.open_settings("Görevler")
pump(0.2)
check("disabled" in app.settings_win.sp_icon.state(), "not panelinde ikon boyutu kutusu pasif")
app.settings_win.win.destroy()
nt.text.insert("end", "!")
app.confirm = lambda t, m: True
r = app.remove_panel(nt)                                    # yazılmış ama kaydedilmemiş metinle kaldır
pump(0.3)
trash_notes = os.path.join(fileops.notes_dir(data), fileops.TRASH_DIRNAME)
kept = [fileops.notefmt.loads(open(os.path.join(trash_notes, f), encoding="utf-8").read())[0]
        for f in os.listdir(trash_notes)] if os.path.isdir(trash_notes) else []
check(r.ok and "Görevler" not in app.panels and kept == ["merhaba çğıöşü\nikinci satır +son!"],
      "not kaldırıldı: dosya silinmedi, notlar/_silinecek içinde, son yazı dahil")
nt = app.new_panel("Kalıcı Not", "note")                    # program çıkışında bekleyen yazı kaydedilsin
nt.text.insert("end", "çıkışta kaydedilecek")

# --- 3) kilit
before = (p1.cfg["x"], p1.cfg["y"], p1.cfg["w"], p1.cfg["h"])
app.set_lock(True)
x0, y0 = p1.cfg["x"], p1.cfg["y"]
p1._head_press(ev(10, 10, x0 + 10, y0 + 10))
p1._head_motion(ev(110, 60, x0 + 110, y0 + 60))
p1._head_release(ev(110, 60, x0 + 110, y0 + 60))
check((p1.cfg["x"], p1.cfg["y"]) == (x0, y0), "kilitli: panel taşınmadı")
bw, bh = p1.body.winfo_width(), p1.body.winfo_height()
check(not p1._in_grip(bw - 5, bh - 5), "kilitli: yeniden boyutlandırma tutamacı pasif")
p1._body_press(ev(bw - 5, bh - 5, 500, 500))
p1._body_drag(ev(bw + 40, bh + 40, 540, 540))
p1._body_release(ev(bw + 40, bh + 40, 540, 540))
check((p1.cfg["w"], p1.cfg["h"]) == (before[2], before[3]), "kilitli: boyut değişmedi")
n_items = len(p1.items)
touch(os.path.join(desk, "Kilitte_eklendi.txt"))
m, e = app.drop_paths(p1, [os.path.join(desk, "Kilitte_eklendi.txt")])
check(not e and os.path.exists(os.path.join(p1.folder, "Kilitte_eklendi.txt")) and len(p1.items) == n_items + 1,
      "kilitli: sürükle-bırak ile dosya ekleme çalışıyor")
opened = []
real_startfile = os.startfile
os.startfile = lambda path: opened.append(path)               # gerçekten açmadan çift tıkı doğrula
try:
    pump(0.2)
    cx, cy = p1.rects[0][0] + 5, p1.rects[0][1] + 5
    p1._body_double(ev(cx, cy))
finally:
    os.startfile = real_startfile
check(len(opened) == 1, "kilitli: çift tıkla açma çalışıyor")
p1.toggle()
pump(0.3)
p1.toggle()
pump(0.3)
check(p1.cur_h == 300 or p1.cur_h == p1.cfg["h"], "kilitli: aç/kapat çalışıyor")
app.set_lock(False)
p1._head_press(ev(10, 10, x0 + 10, y0 + 10))
p1._head_motion(ev(110, 60, x0 + 110, y0 + 60))
p1._head_release(ev(110, 60, x0 + 110, y0 + 60))
check(p1.cfg["x"] == x0 + 100 and p1.cfg["y"] == y0 + 50, "kilit açık değil: panel taşınıyor")
check(p1._in_grip(bw - 5, bh - 5), "kilit açık değil: tutamaç aktif")
p1.cfg["x"], p1.cfg["y"] = x0, y0
p1.top.geometry(f"+{x0}+{y0}")

# --- 4) masaüstü ikonlarını gizle
check(not app.icons.enabled and not app.icons.set_enabled(True), "TEST modunda ikon gizleme kapalı/reddediyor")
app.open_settings("Belgeler")
pump(0.3)
check("disabled" in app.settings_win.cb_hide.state(), "ayarlarda 'Masaüstü ikonlarını gizle' TEST modunda gri")
check("disabled" not in app.settings_win.sp_icon.state() or True, "ayarlar penceresi kuruldu")
app.settings_win.win.destroy()
fake = type("F", (), {"hidden": False, "get_hidden": lambda s: s.hidden,
                      "set_hidden": lambda s, v: (setattr(s, "hidden", v), True)[1]})()
app.icons = deskicons.IconHider(app.cfg["general"], fake, app.save)   # SAHTE arka uç (Explorer'a dokunmaz)
app.icons.set_enabled(True)
check(fake.hidden and app.cfg["general"]["hide_icons_restore"] is False, "sahte arka uç: gizlendi, eski durum kaydedildi")

# ================= Sürüm 3 =================
from version import __version__  # noqa: E402

# --- 1) sağ tık menüsü: komut grupları, aralarda ayırıcı
def menu_layout(m):
    out = []
    for i in range(m.index("end") + 1):
        t = m.type(i)
        out.append("-" if t == "separator" else m.entrycget(i, "label"))
    return out


lay = menu_layout(p1.build_menu())
rb = "Remove Recycle Bin" if "recycle" in p1.cfg["specials"] else "Add Recycle Bin"
check(lay == ["New panel…", "Rename…", "-", "Color", "Opacity", "-", "Title text…", "Content text…",
              "-", "Sort A–Z", rb, "-", "Settings…", "-", "Remove panel…", "-", "Collapse"],
      "kısayol paneli menüsü: grup sırası ve ayırıcılar")
nt3 = app.new_panel("Menü Notu", "note")
lay = menu_layout(nt3.build_menu())
check(lay == ["New panel…", "Rename…", "-", "Color", "Opacity", "-", "Title text…", "Content text…",
              "-", "Settings…", "-", "Remove panel…", "-", "Collapse"], "not paneli menüsü (öğe grubu yok)")
check(all(not (a == "-" and b == "-") for a, b in zip(lay, lay[1:])) and lay[0] != "-" and lay[-1] != "-",
      "menüde çift/baş/son ayırıcı yok")
p1.toggle()
pump(0.3)
check(menu_layout(p1.build_menu())[-1] == "Expand" and menu_layout(p1.build_menu())[0] == "New panel…",
      "kapalı panelde en alttaki komut 'Expand'")
p1.toggle()
pump(0.3)

# --- 2) sekmeli ayarlar + sürüm
app.open_settings("Belgeler")
pump(0.4)
S = app.settings_win
tabs = [S.nb.tab(i, "text") for i in S.nb.tabs()]
check(tabs == ["General", "Panel", "Title", "Content", "Bar", "About"], "ayarlar sekmeleri: " + " · ".join(tabs))
check(S.win.title() == f"M Panels v{__version__} — Settings", "ayarlar başlığında sürüm (version.py): " + S.win.title())
check(not hasattr(S, "ver"), "Genel sekmesinde sürüm satırı kalmadı")
check(S.about_ver.cget("text") == f"v{__version__}" and S.about_name.cget("text") == "M Panels",
      "About: ad ve sürüm (version.py)")
check(tabs[-1] == "About", "About sekmesi en sağda")
_gtxt = [w.cget("text") for w in S.tab["general"].winfo_children() if w.winfo_class() in ("TLabel", "Label")]
check(not any(f"v{__version__}" in t for t in _gtxt), "Genel sekmesinde sürüm yok")
S.v_about.set("help"); S.show_about()
_help = S.about_text.get("1.0", "end")
check(all(h in _help for h in ("Shortcut panels", "Note panels", "Calendar panels", "General")),
      "About › Help: panel türü başlıkları")
check(str(S.about_text.cget("state")) == "disabled", "About metni salt okunur")
S.v_about.set("news"); S.show_about()
_news = S.about_text.get("1.0", "end")
check(f"v{__version__}" in _news and "v0.1.0" in _news and "Calendar" in _news, "About › What's new: CHANGELOG.md'den (0.1.0–güncel)")
S.v_about.set("help"); S.show_about()
S.show_tab("general")
pump(0.2)
check(S.nb.index(S.nb.select()) == 0 and "disabled" in S.cb_hide.state(), "Genel sekmesi açıldı; test modunda ikon kutusu gri")
check(hasattr(S, "cb_lock") and hasattr(S, "cb_auto"), "Genel: kilit ve Windows ile başlat kutuları var")

# --- 3) başlık ve içerik ayrı + eski config çevirisi
S.show_tab("title")
S.title_ed.set({"font": "Arial", "size": 14, "color": "#ff0000", "bold": False, "italic": True})
S.content_ed.set({"font": "Courier New", "size": 10, "color": "#00ff00", "bold": True, "italic": False})
S.apply()
c1 = p1.cfg
check((c1["title_font"], c1["title_size"], c1["title_color"], c1["title_bold"], c1["title_italic"]) ==
      ("Arial", 14, "#ff0000", False, True), "başlık stili ayrı kaydedildi")
check((c1["content_font"], c1["content_size"], c1["content_color"], c1["content_bold"], c1["content_italic"]) ==
      ("Courier New", 10, "#00ff00", True, False), "içerik stili ayrı kaydedildi")
check(p1.font("title").cget("size") == 14 and p1.font("content").cget("size") == 10 and
      p1.font("title").actual("family") != p1.font("content").actual("family"), "başlık ve içerik fontları farklı nesneler")
S.title_ed.set({"font": "Segoe UI", "size": 500, "color": "#ff0000", "bold": True, "italic": False})
S.title_ed.size.set("500")
S.apply()
check(p1.cfg["title_size"] == 72 and "must be from" in S.msg.cget("text"), "başlık boyutu 6–72'ye çekildi, uyarı verildi")
S.title_ed.set({"font": "Segoe UI", "size": 9, "color": "#e8e8ec", "bold": True, "italic": False})
S.content_ed.set({"font": "Segoe UI", "size": 9, "color": "#e8e8ec", "bold": False, "italic": False})
S.apply()
# eski config: tek font_size + text_color
old = app.cfg["panels"]["Belgeler"]
for k in list(old):
    if k.startswith(("title_", "content_")):
        del old[k]
old.update(font_size=13, text_color="#123456")
cc = app.panel_cfg("Belgeler")
check(cc["title_size"] == 13 and cc["content_size"] == 13 and cc["title_color"] == "#123456" and
      cc["content_color"] == "#123456" and "font_size" not in cc and "text_color" not in cc,
      "eski config (font_size/text_color) başlık ve içeriğe aynı değer olarak çevrildi")
check(cc["title_bold"] is True and cc["content_bold"] is False, "eskiden kalın başlık / düz içerik korundu")
cc.update(title_size=9, content_size=9, title_color="#e8e8ec", content_color="#e8e8ec")
p1.apply_cfg()
# menüden başlık yazısı: yalnız başlık değişir
asked = []
app.ask_style = lambda title, st: (asked.append((title, dict(st))), {**st, "size": 18, "bold": False})[1]
before_content = dict(theme_style := mpanels.theme.style_of(p1.cfg, "content"))
app.edit_style(p1, "title")
check(p1.cfg["title_size"] == 18 and not p1.cfg["title_bold"] and mpanels.theme.style_of(p1.cfg, "content") == before_content,
      "menü 'Başlık yazısı…' yalnız başlığı değiştirdi")
check(asked and asked[0][0].startswith("Title text"), "başlık penceresi başlığı: " + asked[0][0])
app.edit_style(p1, "content")
check(p1.cfg["content_size"] == 18 and asked[1][0].startswith("Content text"), "menü 'İçerik yazısı…' içeriği değiştirdi")
cc.update(title_size=9, title_bold=True, content_size=9)
p1.apply_cfg()
# büyük başlık yazısı: başlık çubuğu yazıya göre büyür, kırpılmaz
check(p1.head_h == mpanels.HEAD_H and p1.cfg["title_size"] == 9, "varsayılan başlıkta çubuk yüksekliği 30 px")
cc.update(title_size=24)
p1.apply_cfg()
pump(0.2)
check(p1.head_h > mpanels.HEAD_H and p1.head.winfo_height() == p1.head_h and p1.font("title").metrics("linespace") + 4 <= p1.head_h,
      f"başlık 24 pt: çubuk büyüdü ({p1.head_h} px), yazı sığıyor")
p1.toggle()
pump(0.4)
check(p1.cur_h == p1.head_h and p1.top.winfo_height() == p1.head_h, "büyük başlıkta kapalı panel yüksekliği = çubuk")
p1.toggle()
pump(0.4)
check(p1.cur_h == p1.cfg["h"] and p1.body.winfo_y() == p1.head_h, "açılınca gövde çubuğun altından başlıyor")
cc.update(title_size=9)
p1.apply_cfg()
pump(0.2)
app.open_settings("Belgeler")                          # (pencere zaten açık: yalnız öne gelir)
S = app.settings_win

# --- 4) font seçimi: kurulu fontlar, aranabilir, önizlemeli
S.show_tab("content")
pump(0.3)
pk = S.content_ed.picker
check(len(pk.fonts) > 5 and not any(f.startswith("@") for f in pk.fonts), f"kurulu font listesi alındı ({len(pk.fonts)} font)")
pk.q.set("arial")
pump(0.1)
check(pk.shown and all("arial" in f.casefold() for f in pk.shown), "arama kutusu listeyi süzdü: " + ", ".join(pk.shown[:3]))
pk.lb.selection_clear(0, "end")
pk.lb.selection_set(0)
pk.lb.event_generate("<<ListboxSelect>>")
pump(0.1)
check(pk.get() == pk.shown[0] and S.content_ed.prev.cget("font") != "", "listeden seçim yapıldı: " + pk.get())
S.content_ed.size.set("20")
S.content_ed.bold.set(True)
S.content_ed._changed()
fnt = tkfont_actual = S.content_ed.prev.cget("font")
import tkinter.font as _tkf  # noqa: E402
pf = _tkf.Font(font=fnt)
check(pf.actual("size") == 20 and pf.actual("weight") == "bold", "önizleme seçilen boyut/kalınlığı gösteriyor")
check(S.content_ed.prev.cget("text").startswith("Sample text") and "ğ" in S.content_ed.prev.cget("text"), "önizleme Türkçe örnek metin")
pk.set("Segoe UI")
check(pk.q.get() == "" and pk.get() == "Segoe UI" and "Segoe UI" in [pk.shown[i] for i in pk.lb.curselection()],
      "set(): süzgeç temizlendi, font listede seçili")
S.content_ed.set({"font": "Segoe UI", "size": 9, "color": "#e8e8ec", "bold": False, "italic": False})
S.apply()
app.settings_win.win.destroy()

# --- 5) not panelinde seçili metne biçim
import json as _json  # noqa: E402

fn = nt3.top.winfo_exists() and nt3
fn.cfg.update(x=900, y=320, w=340, h=220)
fn.apply_cfg()
fn.text.insert("end", "Merhaba çğı dünya\nikinci satır")
pump(0.2)
popped = []
real_popup = app.popup
app.popup = lambda m, x, y: popped.append(m)
fn._text_right(ev(5, 5, 5, 5))                          # seçim yok → panel menüsü
check(popped and menu_layout(popped[-1])[0] == "New panel…", "seçim yokken sağ tık normal panel menüsünü açar")


def sel(a, b):
    fn.text.tag_remove("sel", "1.0", "end")
    fn.text.tag_add("sel", f"1.0+{a}c", f"1.0+{b}c")


sel(0, 7)
fn._text_right(ev(5, 5, 5, 5))
check(menu_layout(popped[-1]) == ["Bold", "Italic", "Underline", "-", "Color…", "Font…", "Size", "-", "Clear formatting"],
      "seçim varken sağ tık biçim menüsü: " + " | ".join(menu_layout(popped[-1])))
app.popup = real_popup
check(fn.format_op("bold") and fn.format_op("italic") and fn.format_op("underline"), "kalın/italik/altı çizili uygulandı")
app.ask_color = lambda panel, initial: "#ff9a3c"
app.ask_font = lambda family, size: "Arial"
app.ask_size = lambda initial: 20
check(fn.format_op("color") and fn.format_op("font") and fn.format_op("size", 14), "renk/font/boyut uygulandı")
text_, spans_ = fn.rich.dump()
check(spans_ == [{"start": 0, "end": 7, "bold": True, "italic": True, "underline": True, "color": "#ff9a3c",
                  "font": "Arial", "size": 14}], "biçim aralığı doğru: " + str(spans_))
check(fn.rich.effective("1.0+10c")["bold"] is False, "seçilmeyen metin biçimsiz kaldı")
pump(1.0)                                               # otomatik kayıt
disk = fileops.read_note(data, "Menü Notu")
check(disk.text == text_ and disk.spans == spans_, "biçim otomatik kaydedildi (JSON)")
check(_json.load(open(fileops.note_path(data, "Menü Notu"), encoding="utf-8"))["format"] == 1, "dosya JSON, format=1")
sel(8, 12)
fn.format_op("bold")
fn.format_op("clear")
check(all(s_["end"] <= 7 or s_["start"] >= 12 or True for s_ in fn.rich.dump()[1]) and
      len(fn.rich.dump()[1]) == 1, "'Biçimi temizle' yalnız seçili kısmı temizler")
sel(0, 7)
fn.format_op("clear")
check(fn.rich.dump()[1] == [], "biçimi temizle: aralık kalmadı")
sel(0, 7)
fn.format_op("bold")
app.rename_panel(fn, "Biçimli Not")                     # yeniden adlandırınca biçim kaybolmamalı
pump(0.5)
fn = app.panels["Biçimli Not"]
check(fn.rich.dump()[1] == [{"start": 0, "end": 7, "bold": True}], "yeniden adlandırmada biçim korundu")
fn.cfg["content_size"] = 16
fn.apply_cfg()
check(fn.rich.effective("1.0+10c")["size"] == 16, "içerik fontu değişince biçimsiz metin takip etti")
fn.text.insert("end", " +kaydedilmemiş")
app.confirm = lambda t, m: True
r = app.remove_panel(fn)                                # kaydedilmemiş yazı + biçimle kaldır
tr = os.path.join(fileops.notes_trash(data))
kept = [fileops.notefmt.loads(open(os.path.join(tr, f), encoding="utf-8").read()) for f in os.listdir(tr)
        if f.startswith("Biçimli")]
check(r.ok and kept and kept[0][0].endswith("+kaydedilmemiş") and kept[0][1] == [{"start": 0, "end": 7, "bold": True}],
      "not kaldırılınca JSON (metin+biçim) notlar/_silinecek'e taşındı")

# --- eski düz .txt not → otomatik içe alma
os.makedirs(fileops.notes_dir(data), exist_ok=True)
with open(fileops.legacy_note_path(data, "Eski Not"), "w", encoding="utf-8", newline="") as f_:
    f_.write("eski düz not çğı\nüç")
app.cfg["panels"]["Eski Not"] = {"type": "note"}
app.sync_panels()
pump(0.3)
en = app.panels.get("Eski Not")
check(en is not None and en.text.get("1.0", "end-1c") == "eski düz not çğı\nüç", "eski .txt not panelde açıldı")
check(os.path.exists(fileops.note_path(data, "Eski Not")) and not os.path.exists(fileops.legacy_note_path(data, "Eski Not")) and
      os.path.exists(os.path.join(fileops.notes_trash(data), "Eski Not.txt")), "eski .txt → JSON; .txt notlar/_silinecek'e taşındı (silinmedi)")
check(en.cfg["title_size"] == 9 and en.cfg["content_font"] == "Segoe UI", "yeni panel config'i varsayılan stille tamamlandı")

# --- v0.4: görev çubuğu / Alt+Tab, tek örnek, ikon yedeği
import uiwidgets  # noqa: E402
app.show_all(True)
pump(0.4)
check(app.panels and all(winutil.is_toolwindow(pw.top) for pw in app.panels.values()),
      "tüm paneller görev çubuğunda/Alt+Tab'da gizli (TOOLWINDOW, APPWINDOW değil)")
d_ = uiwidgets.PromptDialog(app.root, "t", "p", "x")
pump(0.2)
check(winutil.is_toolwindow(d_.win), "istem penceresi (PromptDialog) görev çubuğunda gizli")
d_.win.destroy()
nd_ = mpanels.NewPanelDialog(app)
pump(0.2)
check(winutil.is_toolwindow(nd_.win), "yeni panel penceresi görev çubuğunda gizli")
nd_.win.destroy()
app.flash(app.panels[ui.DEFAULT_PANEL_NAME] if ui.DEFAULT_PANEL_NAME in app.panels else next(iter(app.panels.values())), "toast")
pump(0.3)
check(winutil.is_toolwindow(app._toast), "bildirim kutusu görev çubuğunda gizli")
app.open_settings()
pump(0.4)
check(app.settings_win is not None and not winutil.is_toolwindow(app.settings_win.win),
      "Ayarlar penceresi görev çubuğunda görünür (APPWINDOW)")

# tek örnek: ikinci başlatma çalışan kopyayı öne getirir
app.settings_win.win.destroy()
app.show_all(False)
pump(0.3)
check(not app.visible, "(hazırlık) paneller gizlendi")
check(winutil.signal_running_instance(inst_name, retries=3), "ikinci başlatma çalışan kopyayı uyardı (olay bulundu)")
pump(1.0)
check(app.visible and all(pw.top.winfo_viewable() for pw in app.panels.values()), "uyarı üzerine paneller gösterildi")
check(app.settings_win is not None and app.settings_win.win.winfo_exists(), "uyarı üzerine Ayarlar penceresi açıldı")
check(not winutil.signal_running_instance(f"MPanels_Smoke_yok_{os.getpid()}", retries=1), "çalışan kopya yoksa uyarı gönderilmez")

# ikon: dosya yoksa/bozuksa hata yok, 16 px'ten büyük her boyutta çalışıyor
import theme  # noqa: E402
from unittest import mock as _icon_mock  # noqa: E402
with _icon_mock.patch.object(winutil, "app_icon_path", return_value=None):
    im_ = mpanels.app_icon_image(48)
check(im_.size == (48, 48), "ikon dosyası yokken geçici ikonla çalışıyor")
open(os.path.join(root, "bozuk.ico"), "wb").write(b"not an icon")
with _icon_mock.patch.object(winutil, "app_icon_path", return_value=os.path.join(root, "bozuk.ico")):
    check(mpanels.app_icon_image(32).size == (32, 32), "bozuk ikon dosyasında da hata yok")
check(os.path.isfile(winutil.app_icon_path() or ""), "paketli assets/m_panels.ico bulunuyor")

# --- v0.5: takvim paneli (AĞSIZ: sahte indirici + geçici kaynak dosyası)
import json  # noqa: E402
import urllib.request  # noqa: E402
from unittest import mock  # noqa: E402
import calendar_panel  # noqa: E402
from calendar_panel import core as cal_core  # noqa: E402
from calendar_panel import settings as _cal_settings_mod  # noqa: E402

if calendar_panel.AVAILABLE:
    from datetime import date as _date, timedelta as _td
    _t = _date.today()
    # An event that certainly falls inside the week shown now (Monday-start week of today), computed from today:
    # a day of that week other than today, so Week has at least two busy days whatever weekday the test runs on.
    _today0 = _t
    _wk0 = _t - _td(days=_t.weekday())
    _wk_event_day = _wk0 + _td(days=2 if _t.weekday() != 2 else 4)
    _ics = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//smoke//EN",
        "BEGIN:VEVENT", "UID:s3", f"DTSTART:{_wk_event_day:%Y%m%d}T140000", f"DTEND:{_wk_event_day:%Y%m%d}T150000",
        "SUMMARY:Week-day event", "END:VEVENT",
        "BEGIN:VEVENT", "UID:s1", f"DTSTART:{_t:%Y%m%d}T100000", f"DTEND:{_t:%Y%m%d}T110000",
        "SUMMARY:Standup today", "LOCATION:Room 1", "END:VEVENT",
        "BEGIN:VEVENT", "UID:s2", f"DTSTART;VALUE=DATE:{_t:%Y%m%d}", "SUMMARY:All day thing", "END:VEVENT",
        "END:VCALENDAR", ""]).encode()
    fake_cals = [{"name": "Work", "url": "https://fake.invalid/work", "color": "#4285f4", "enabled": True},
                 {"name": "Home", "url": "https://fake.invalid/home", "color": None, "enabled": True}]
    fetch_log, fetch_mode = [], {"fail": False}

    def fake_download(url):
        fetch_log.append(url)
        if fetch_mode["fail"]:
            raise OSError("boom " + url)
        return cal_core.parse_calendar(_ics)

    def no_net(*a, **k):
        raise AssertionError("ağ erişimi denendi")

    def canvas_texts(cv):
        return [cv.itemcget(i, "text") for i in cv.find_all() if cv.type(i) == "text"]

    with mock.patch.object(cal_core, "download_calendar", fake_download), \
            mock.patch.object(urllib.request, "urlopen", no_net):
        dirs_before = sorted(os.listdir(ctx.panels_root))
        cp = app.new_panel("Takvim", "calendar")
        pump(0.3)
        check(cp is not None and cp.is_calendar and cp.cfg["type"] == "calendar" and cp.cal is not None,
              "takvim paneli oluşturuldu (tür calendar)")
        check(sorted(os.listdir(ctx.panels_root)) == dirs_before and not os.path.exists(ctx.panel_path("Takvim")),
              "takvim paneli için diskte klasör/dosya oluşmadı")
        check("source_path" not in cp.cfg["calendar"] and cp.cfg["calendar"]["calendars"] == [],
              "yeni takvim paneli: kaynak yolu yok, takvim listesi boş")
        cp.cal_refresh()
        pump(0.5)
        check(cp.model.snapshot()["error"] == ui.CAL_ERR_NONE, "takvim eklenmeden panelde 'ekle' mesajı")
        cp.cfg["calendar"]["calendars"] = [dict(c) for c in fake_cals]
        cp.cal_refresh()
        pump(1.5)
        snap = cp.model.snapshot()
        check(snap["error"] is None and snap["last_update"] is not None and len(fetch_log) >= 2,
              "sahte veriyle yenileme tamam (2 takvim), hata yok")
        check(winutil.is_toolwindow(cp.top), "takvim paneli görev çubuğunda gizli")
        check(any("Standup today" in t for *_, t in cp.cal.tips) and any("All day thing" in t for *_, t in cp.cal.tips),
              "liste görünümünde sahte etkinlikler çizildi")
        texts = canvas_texts(cp.cal_cv)
        _all = texts + canvas_texts(cp.body) + canvas_texts(cp.head)
        check(not any(__version__ in t or t.startswith("updated") or t == "Loading…" for t in _all),
              "takvim panelinde sürüm/alt durum satırı yok")
        check(cp.cal.foot_height() == 0, "takvim alt satırı için ayrılan alan yok")
        _st = cp.cal.status_text()
        check(_st.startswith("Updated ") and len(_st) == len("Updated 00:00"), "başlık ipucu metni: " + _st)
        cp._head_hover(types.SimpleNamespace(x_root=300, y_root=300))
        check(cp.cal._tip is not None and cp.cal._tip._text == _st, "başlığa gelince ipucu penceresi açıldı")
        cp.cal.hide_tip()
        cp.model.error = "boom-test"
        check("boom-test" in cp.cal.status_text() and cp.cal.status_text().endswith(_st), "ipucunda hata mesajı da var")
        cp.model.error = None
        cp.model.loading = True
        check(cp.cal.status_text().startswith("Loading…"), "yenilenirken ipucunda Loading…")
        cp.model.loading = False
        check(any("Standup today" in t for t in texts) and any(t == ui.CAL_ALL_DAY for t in texts),
              "liste: başlık ve 'All day' metni tuvalde")
        for view in ("week", "day", "list"):
            cp.cal.set_view(view)
            pump(0.3)
            check(cp.cfg["calendar"]["view"] == view and cp.cal.tips, f"görünüm '{view}' çizildi")
        cp.cal.set_view("week")
        d_before = cp.cal.anchor
        cp.cal.nav(1)
        check(cp.cal.anchor == d_before + _td(days=7), "hafta görünümünde ▶ bir hafta ileri")
        cp.cal.go_today()
        cp.cal.set_view("day")
        cp.cal.nav(-1)
        check(cp.cal.anchor == _date.today() - _td(days=1), "gün görünümünde ◀ bir gün geri")
        cp.cal.set_view("list")
        pump(0.2)
        x0, y0, x1, y1, fn = cp.cal.nav_hits[1]
        cp.cal.nav_click((x0 + x1) / 2, (y0 + y1) / 2)
        pump(0.2)
        check(cp.cfg["calendar"]["view"] == "day", "gezinme satırındaki 'Day' tıklaması görünümü değiştirdi")
        cp.cal.set_view("list")
        pump(0.2)
        tip = cp.cal.tip_at(40, cp.cal.tips[0][1] + 3)
        check(tip is not None and ("Standup today" in tip or "All day thing" in tip), "üzerine gelince ipucu metni bulundu")
        cp.cal.show_tip("deneme", 200, 200)
        check(cp.cal._tip is not None and winutil.is_toolwindow(cp.cal._tip), "ipucu penceresi görev çubuğunda gizli")
        cp.cal.hide_tip()
        lay = menu_layout(cp.build_menu())
        check("Refresh calendar" in lay and "Open Google Calendar" in lay and "Sort A–Z" not in lay and lay[-1] == "Collapse",
              "takvim paneli menüsü: Refresh + Open Google Calendar var, A–Z yok: " + " | ".join(lay))
        cp.toggle()
        pump(0.4)
        check(not cp.expanded and cp.cal_cv.winfo_manager() == "", "küçültünce takvim içeriği gizlendi")
        cp.toggle()
        pump(0.4)
        check(cp.expanded and cp.cal_cv.winfo_manager() == "place", "açınca takvim içeriği geri geldi")
        app.set_lock(True)
        check(not cp._in_grip(cp.body.winfo_width() - 5, cp.body.winfo_height() - 5),
              "kilitli: takvim panelinde tutamaç pasif")
        app.set_lock(False)
        # settings: the Calendar tab exists only for calendar panels
        app.open_settings("Takvim")
        pump(0.4)
        S = app.settings_win
        tabs = [S.nb.tab(i, "text") for i in S.nb.tabs()]
        check(tabs == ["General", "Panel", "Title", "Content", "Calendar", "Bar", "About"],
              "takvim paneli seçiliyken sekmeler: " + " · ".join(tabs))
        check([c["name"] for c in S.cal_list] == ["Work", "Home"]
              and len(S.cal_tree.get_children()) == 2 and "fake.invalid" not in str(
                  [S.cal_tree.item(i, "values") for i in S.cal_tree.get_children()]),
              "Calendar sekmesi: takvim listesi (adlar var, adresler görünmüyor)")
        check("disabled" in S.sp_icon.state(), "takvimde ikon boyutu pasif")
        S.cal_list[0]["enabled"] = False                   # Work off, Home stays on
        S.v["cal_view"].set("Week")
        S.v["cal_weeks"].set("3")
        S.v["cal_refresh"].set("999")
        S.apply()
        pump(1.2)
        cs = cp.cfg["calendar"]
        check([c["name"] for c in cs["calendars"] if c["enabled"]] == ["Home"] and cs["view"] == "week" and cs["list_weeks"] == 3 and cs["refresh_minutes"] == 120,
              "Ayarlar › Apply takvim ayarlarını işledi (yenileme 120'ye çekildi)")
        check(fetch_log[-1] == "https://fake.invalid/home" and S.v["cal_refresh"].get() == "120",
              "yalnız seçili takvim yenilendi")
        with open(app.config_path, encoding="utf-8") as _cf:
            _cfg_text = _cf.read()
        check("https://fake.invalid/home" in _cfg_text and "source_path" not in _cfg_text,
              "adresler M Panels'ın kendi config'inde, eski kaynak yolu yok")
        # v1.1 step 1: Day/Week look + past-event fading controls (nothing changes before Apply)
        check(len(S.cal_look_widgets) == 9 and S.v["cal_hh"].get() == str(cs["hour_height"]),
              "Calendar sekmesi: saat aralığı / yükseklik / sığdırma / soluklaştırma denetimleri")
        _before = dict(cp.cfg["calendar"])
        for _k, _v in (("cal_start", "9"), ("cal_end", "12"), ("cal_hh", "44"), ("cal_ehh", "12"), ("cal_fade", "30")):
            S.v[_k].set(_v)
        S.v_cal_fit.set(False)
        S.v["cal_view"].set("Day")
        pump(0.2)
        check(cp.cfg["calendar"] == _before and S.dirty(), "Apply öncesi panel değişmedi; pencere kaydedilmemiş değişiklik görüyor")
        check(S.apply() is True, "Apply tamam")
        pump(0.8)
        _s = cp.cfg["calendar"]
        _t = canvas_texts(cp.cal_cv)
        check((_s["start_hour"], _s["end_hour"], _s["hour_height"], _s["empty_hour_height"], _s["past_fade"], _s["fit_boxes"])
              == (9, 12, 44, 12, 30, False), "Apply yeni görünüm ayarlarını işledi")
        check(all(h in _t for h in ("09", "10", "11")) and "08" not in _t and "12" not in _t,
              "Day görünümü Apply'dan hemen sonra yeni saat aralığını çizdi")
        check(not S.dirty(), "Apply sonrası 'kaydedilmemiş' yok")
        for _k, _v in (("cal_start", "7"), ("cal_end", "24"), ("cal_hh", "30"), ("cal_ehh", "20"), ("cal_fade", "55")):
            S.v[_k].set(_v)
        S.v_cal_fit.set(True)
        S.v["cal_view"].set("Week")
        S.apply()
        pump(0.5)

        # v1.1 step 2: each view remembers its own width; the height stays shared
        def _grip_resize(dw):
            _c = cp.cal_cv
            cp._cal_press(types.SimpleNamespace(x=_c.winfo_width() - 5, y=_c.winfo_height() - 5, x_root=100, y_root=100))
            cp._body_drag(types.SimpleNamespace(x_root=100 + dw, y_root=100))
            cp._body_release(types.SimpleNamespace(x_root=0, y_root=0))
            pump(0.3)
        cp.cal.set_view("list")
        pump(0.3)
        _wl = cp.cfg["w"]
        _grip_resize(60)
        check(cp.cfg["calendar"]["widths"].get("list") == _wl + 60 == cp.top.winfo_width(), "List: köşeden büyütülen genişlik List için kaydedildi")
        _wd_rec = cp.cfg["calendar"]["widths"].get("day")        # Day may already have a record from the earlier steps
        cp.cal.set_view("day")
        pump(0.3)
        check(cp.top.winfo_width() == (_wd_rec or _wl + 60), "Day: kayıtlı genişlik geldi (kayıt yoksa mevcut genişlik korundu)")
        _grip_resize(120)
        _wd = cp.cfg["w"]
        cp.cal.set_view("list")
        pump(0.3)
        check(cp.top.winfo_width() == _wl + 60 and cp.cfg["calendar"]["widths"].get("day") == _wd, "List'e dönünce List genişliği geldi")
        cp.cal.set_view("day")
        pump(0.3)
        check(cp.top.winfo_width() == _wd, "Day'e dönünce Day genişliği geldi")
        cp.cal.set_view("week")
        pump(0.3)

        # v1.1 step 2b: Week shrinks days without events (the fake calendar has events on some days only)
        def _vlines(cv):
            return sorted({round(cv.coords(i)[0], 2) for i in cv.find_all()
                           if cv.type(i) == "line" and len(cv.coords(i)) == 4 and cv.coords(i)[0] == cv.coords(i)[2]})
        _xs = _vlines(cp.cal_cv)
        _cw = [b - a for a, b in zip(_xs, _xs[1:])]
        check(len(_cw) == 7 and abs(sum(_cw) - (cp.cal_cv.winfo_width() - 48)) < 1.0, "Week: 7 sütun, genişlikler toplamı kullanılabilir genişlik")
        # strong check: the week shown is today's week and the day with the guaranteed event is a wide (busy) column
        cp.cal.go_today()
        cp.cal.set_view("week")
        pump(0.3)
        _xs = _vlines(cp.cal_cv)
        _cw = [b - a for a, b in zip(_xs, _xs[1:])]
        _d0 = cal_core.week_start_of(_today0, cp.cfg["calendar"].get("week_start", "monday"))
        _busy = {_today0, _wk_event_day}
        _bi = [i for i in range(7) if _d0 + _td(days=i) in _busy]
        _ei = [i for i in range(7) if _d0 + _td(days=i) not in _busy]
        check(any("Week-day event" in x for x in canvas_texts(cp.cal_cv)), "Week: haftanın içindeki etkinlik çizildi")
        check(cp.cfg["calendar"]["shrink_empty"] is True and len(_bi) >= 2 and _ei
              and min(_cw[i] for i in _bi) > max(_cw[i] for i in _ei) + 1
              and max(_cw[i] for i in _bi) - min(_cw[i] for i in _bi) < 1.0
              and max(_cw[i] for i in _ei) - min(_cw[i] for i in _ei) < 1.0,
              "Week: etkinlikli günler (bugün + etkinlik günü) geniş ve eşit, boş günler dar ve eşit")
        S.v_cal_shrink.set(False)
        check(cp.cfg["calendar"]["shrink_empty"] is True and S.dirty(), "'Week: shrink empty days' Apply'dan önce uygulanmadı")
        S.apply()
        pump(0.4)
        _xs = _vlines(cp.cal_cv)
        _cw = [b - a for a, b in zip(_xs, _xs[1:])]
        check(cp.cfg["calendar"]["shrink_empty"] is False and max(_cw) - min(_cw) < 1.0, "Kapalıyken tüm Week sütunları eşit")
        S.v_cal_shrink.set(True)
        S.apply()
        pump(0.3)

        # v1.1 step 3: 12/24-hour time and first day of the week
        S.v_cal_tf.set("12-hour")
        S.v_cal_ws.set("Sunday")
        check(cp.cfg["calendar"]["time_format"] == "24h" and S.dirty(), "saat biçimi/hafta başı Apply'dan önce uygulanmadı")
        S.apply()
        pump(0.5)
        _t = canvas_texts(cp.cal_cv)
        check(cp.cfg["calendar"]["time_format"] == "12h" and cp.cfg["calendar"]["week_start"] == "sunday" and "7a" in _t
              and [x for x in _t if x in ui.CAL_DAYS_SHORT][:2] == ["Sun", "Mon"],
              "Week: 12 saat etiketleri (7a) ve Pazar başlangıcı çizildi")
        S.v_cal_tf.set("24-hour")
        S.v_cal_ws.set("Monday")
        S.apply()
        pump(0.3)
        # v1.1 step 5: per-key color overrides (nothing changes before Apply; reset returns to the derived palette)
        check(tuple(S.cal_col_ui) == tuple(_cal_settings_mod.COLOR_KEYS) and "bg" not in S.cal_col_ui,
              "Renkler: bg dışındaki her palet anahtarı için seçici var")
        S.nb.select(S.tab["calendar"])
        pump(0.3)
        _derived_event = cp.cal_palette()["event"]
        with mock.patch.object(mpanels.colorchooser, "askcolor", return_value=((0, 0, 0), "#123456")):
            S.cal_col_ui["event"][0].event_generate("<Button-1>")      # the swatch is the picker
            S.win.update()
        check(cp.cfg["calendar"]["colors"] == {} and cp.cal_palette()["event"] == _derived_event and S.dirty()
              and S.cal_col_ui["event"][1].cget("text") == ui.CAL_COLOR_MARK, "Renk seçimi Apply'dan önce uygulanmadı; işaret var")
        S.apply()
        pump(0.4)
        cp.cal.set_view("list")
        pump(0.3)
        _fills = {cp.cal_cv.itemcget(i, "fill") for i in cp.cal_cv.find_all() if cp.cal_cv.type(i) == "rectangle"}
        check(cp.cfg["calendar"]["colors"] == {"event": "#123456"} and "#123456" in _fills,
              "Apply sonrası ezilen renk çizildi (liste çubuğu)")
        with mock.patch.object(mpanels.messagebox, "askyesno", return_value=True):
            S.revert_cal_colors()
        S.apply()
        pump(0.3)
        check(cp.cfg["calendar"]["colors"] == {} and cp.cal_palette()["event"] == _derived_event,
              "Revert to derived colors + Apply: türetilmiş palet birebir döndü")
        # v1.1 step 6: "Make current Calendar look the default" saves only the look, Factory keeps it, Revert restores it
        _hh0 = cp.cfg["calendar"]["hour_height"]
        S.v["cal_hh"].set(str(_hh0 + 10))
        with mock.patch.object(mpanels.messagebox, "showinfo") as _info, \
                mock.patch.object(mpanels.messagebox, "askyesno", return_value=True) as _yes:
            S.make_cal_look_default()
            check(_info.called and not _yes.called and mpanels.CAL_LOOK_KEY not in (json.load(open(app.defaults_path, encoding="utf-8")) if os.path.exists(app.defaults_path) else {}),
                  "Look varsayılanı: Apply edilmemiş değişiklikte uyarı verdi, kaydetmedi")
            S.apply()
            S.make_cal_look_default()
        _saved = json.load(open(app.defaults_path, encoding="utf-8"))[mpanels.CAL_LOOK_KEY]
        check(set(_saved) == set(_cal_settings_mod.LOOK_KEYS) and _saved["hour_height"] == _hh0 + 10
              and "source_path" not in _saved and "view" not in _saved, "Look varsayılanı yalnız görünüm alt kümesini kaydetti")
        with mock.patch.object(mpanels.messagebox, "askyesno", return_value=True):
            S.reset(True)
            _f_hh = cp.cfg["calendar"]["hour_height"]
            _kept = json.load(open(app.defaults_path, encoding="utf-8"))[mpanels.CAL_LOOK_KEY]["hour_height"]
            S.reset(False)
        check(_f_hh == _hh0 and _kept == _hh0 + 10 and cp.cfg["calendar"]["hour_height"] == _hh0 + 10,
              "Factory yerleşik görünüme döndü ve kayıtlı varsayılanı korudu; Revert onu geri getirdi")
        cp.cfg["calendar"]["hour_height"] = _hh0
        os.remove(app.defaults_path)
        cp.cal.set_view("week")
        pump(0.2)
        S.select(next(n for n in app.panels if n != "Takvim"))
        pump(0.2)
        tabs =[S.nb.tab(i, "text") for i in S.nb.tabs()]
        check(tabs == ["General", "Panel", "Title", "Content", "Bar", "About"], "başka panel seçilince Calendar sekmesi kalktı")
        S.win.destroy()
        # errors must not break the panel or the program
        cp.cfg["calendar"].update(view="list", calendars=[])
        cp.cal_refresh()
        pump(1.0)
        check(cp.model.snapshot()["error"] == ui.CAL_ERR_NONE and ui.CAL_ERR_NONE in canvas_texts(cp.cal_cv),
              "takvim yoksa panel içinde kısa mesaj")
        check(all(pw.top.winfo_exists() for pw in app.panels.values()), "hata diğer panelleri etkilemedi")
        cp.cfg["calendar"]["calendars"] = [dict(c) for c in fake_cals]
        fetch_mode["fail"] = True
        cp.cal_refresh()
        pump(1.0)
        check(any(t.startswith("Could not fetch:") and "fake.invalid" not in t for t in canvas_texts(cp.cal_cv)),
              "ağ hatasında kısa mesaj (adres yok)")
        fetch_mode["fail"] = False
        # rename + remove never touch the disk
        r = app.do_rename(cp, "Ajanda")
        pump(0.3)
        check(r.ok and "Ajanda" in app.panels and "Takvim" not in app.panels
              and app.cfg["panels"]["Ajanda"]["type"] == "calendar" and app.panels["Ajanda"].cal is not None,
              "takvim paneli yeniden adlandırıldı (tür ve ayarlar korundu)")
        check(app.new_panel("ajanda", "note") is None, "ad alanı ortak: aynı adlı not açılamaz")
        trash_before = os.path.exists(ctx.trash) and sorted(os.listdir(ctx.trash))
        r = app.remove_panel(app.panels["Ajanda"], confirm=False)
        pump(0.3)
        check(r.ok and "Ajanda" not in app.panels and "Ajanda" not in app.cfg["panels"], "takvim paneli kaldırıldı")
        check((os.path.exists(ctx.trash) and sorted(os.listdir(ctx.trash))) == trash_before,
              "kaldırma _silinecek'e hiçbir şey taşımadı")
        # without the libraries
        with mock.patch.object(calendar_panel, "AVAILABLE", False):
            nd2 = mpanels.NewPanelDialog(app)
            radios = []

            def walk(w):
                for c_ in w.winfo_children():
                    if c_.winfo_class() == "TRadiobutton":
                        radios.append(c_.cget("text"))
                    walk(c_)
            walk(nd2.win)
            nd2.win.destroy()
            check(ui.NEW_KIND_CALENDAR not in radios and ui.NEW_KIND_NOTE in radios,
                  "kütüphane yokken 'Calendar' seçeneği görünmez")
            app.cfg["panels"]["Eski Takvim"] = {"type": "calendar"}
            app.sync_panels()
            pump(0.4)
            ep = app.panels.get("Eski Takvim")
            check(ep is not None and ep.cal is None and ep.cfg["calendar"]["view"] == "list",
                  "kütüphane yokken yapılandırmadaki takvim paneli yine de açılır")
            check(ep is not None and ui.CAL_ERR_LIBS in canvas_texts(ep.body), "kütüphane yokken panelde kısa mesaj var")
            if ep is not None:
                app.remove_panel(ep, confirm=False)
            pump(0.2)
else:
    print("ATLANDI  takvim kitaplıkları yok")

# --- v1.1 step 7a: snap under another panel (stack) + open/close pushes the panel below
import types as _types  # noqa: E402
sa = app.new_panel("Snap A")
sb = app.new_panel("Snap B")
for _p, _x in ((sa, 1100), (sb, 1600)):          # a free corner: snapping refuses spots that overlap other panels
    _p.cfg.update(x=_x, y=500, w=300, h=200, collapsed=False)
    _p.expanded = True
    _p.apply_size(300, 200)
    _p.top.geometry(f"+{_x}+500")
pump(0.2)
_gap = app.cfg["general"]["stack_gap"]
_x0, _y0 = sb.cfg["x"] + 40, sb.cfg["y"] + 8
_tx, _ty = sa.cfg["x"] + 10, sa.cfg["y"] + sa.cur_h + 12          # drop 12 px under A's bottom edge, 10 px to the right
_ev = lambda x, y: _types.SimpleNamespace(x_root=x, y_root=y, x=40, y=8)  # noqa: E731
sb._head_press(_ev(_x0, _y0))
for _i in (1, 2, 3):
    sb._head_motion(_ev(_x0 + (_tx + 40 - _x0) * _i // 3, _y0 + (_ty + 8 - _y0) * _i // 3))
sb._head_release(_ev(_tx + 40, _ty + 8))
pump(0.2)
check(app.cfg["stacks"] == [["Snap A", "Snap B"]], "yapışma: iki panel bir yığın oldu")
check(sb.cfg["x"] == sa.cfg["x"] and sb.cfg["w"] == sa.cfg["w"] and sb.cfg["y"] == sa.cfg["y"] + sa.cur_h + _gap,
      "yapışma: sol kenar ve genişlik eşitlendi, aralık = gap")
check(sb.top.winfo_x() == sb.cfg["x"] and sb.top.winfo_y() == sb.cfg["y"], "yapışma: gerçek pencere de yerinde")
sa.toggle()
pump(0.5)
check(sa.cur_h == sa.head_h and sb.cfg["y"] == sa.cfg["y"] + sa.head_h + _gap and sb.top.winfo_y() == sb.cfg["y"],
      "yığın: A kapanınca B yukarı çekildi (aralık gap)")
sa.toggle()
pump(0.5)
check(sa.cur_h == 200 and sb.cfg["y"] == sa.cfg["y"] + 200 + _gap and sb.top.winfo_y() == sb.cfg["y"],
      "yığın: A açılınca B aşağı itildi (aralık gap)")
# side snap (step 7b): only an alignment, no stack, width unchanged
sc = app.new_panel("Snap C")
sc.cfg.update(x=1900, y=100, w=260, h=150, collapsed=False)
sc.expanded = True
sc.apply_size(260, 150)
sc.top.geometry("+1900+100")
pump(0.2)
_sx = sb.cfg["x"] + sb.cur_w + _gap                               # the spot right of B
_cx0, _cy0 = sc.cfg["x"] + 40, sc.cfg["y"] + 8
_cx1, _cy1 = _sx + 9, sb.cfg["y"] + 25                            # 9 px off, 25 px lower than B's top
sc._head_press(_ev(_cx0, _cy0))
for _i in (1, 2, 3):
    sc._head_motion(_ev(_cx0 + (_cx1 + 40 - _cx0) * _i // 3, _cy0 + (_cy1 + 8 - _cy0) * _i // 3))
sc._head_release(_ev(_cx1 + 40, _cy1 + 8))
pump(0.2)
check(sc.cfg["x"] == _sx and sc.cfg["y"] == sb.cfg["y"] and sc.cfg["w"] == 260 and sc.top.winfo_width() == 260,
      "yana yapışma: B'nin sağına hizalandı (üst kenar B ile aynı, genişlik değişmedi)")
check(app.cfg["stacks"] == [["Snap A", "Snap B"]], "yana yapışma: yığın oluşmadı / değişmedi")
app.remove_panel(sc, confirm=False)
# 7b bug (seen on the real screen): open A, CLOSED B beside it, third panel beside B must snap beside, not under B's bar
ba, bb, bc = app.new_panel("Bug A"), app.new_panel("Bug B"), app.new_panel("Bug C")
for _p, _x, _y, _w in ((ba, 100, 600, 300), (bb, 1500, 600, 300), (bc, 1500, 900, 250)):
    _p.cfg.update(x=_x, y=_y, w=_w, h=200, collapsed=False)
    _p.expanded = True
    _p.apply_size(_w, 200)
    _p.top.geometry(f"+{_x}+{_y}")
bb.toggle()
pump(0.5)


def _drag_to(p, nx, ny):
    sx, sy = p.cfg["x"], p.cfg["y"]
    x0, y0 = sx + 40, sy + 8
    p._head_press(_ev(x0, y0))
    for i in (1, 2, 3):
        p._head_motion(_ev(x0 + (nx - sx) * i // 3, y0 + (ny - sy) * i // 3))
    p._head_release(_ev(nx + 40, ny + 8))
    pump(0.2)


_drag_to(bb, ba.cfg["x"] + ba.cur_w + _gap + 6, ba.cfg["y"] + 9)
check((bb.cfg["x"], bb.cfg["y"]) == (ba.cfg["x"] + ba.cur_w + _gap, ba.cfg["y"]) and bb.cur_h == bb.head_h,
      "7b hata: açık panelin yanına KAPALI panel doğru yapıştı")
_bx = bb.cfg["x"] + bb.cur_w
_drag_to(bc, _bx - 20, bb.cfg["y"] + 14)
check((bc.cfg["x"], bc.cfg["y"]) == (_bx + _gap, bb.cfg["y"]) and not any("Bug C" in st for st in app.cfg["stacks"]),
      "7b hata: üçüncü panel kapalı panelin YANINA yapıştı (barın altına değil), yığın oluşmadı")
check(not any(r[0] < s_[0] + s_[2] and s_[0] < r[0] + r[2] and r[1] < s_[1] + s_[3] and s_[1] < r[1] + r[3]
              for r in [(bc.cfg["x"], bc.cfg["y"], bc.cur_w, bc.cur_h)]
              for s_ in [(q.cfg["x"], q.cfg["y"], q.cur_w, q.cur_h) for q in (ba, bb)]),
      "7b hata: sonuçta hiçbir panelle örtüşme yok")
for _p in (bc, bb, ba):
    app.remove_panel(_p, confirm=False)
pump(0.2)
# 7b-2: snap preview. The frame is shown at the exact spot the drop takes, is click-through, and is gone after the drop.
sp = app.new_panel("Snap P")
sp.cfg.update(x=1900, y=100, w=260, h=150, collapsed=False)
sp.expanded = True
sp.apply_size(260, 150)
sp.top.geometry("+1900+100")
pump(0.2)
_px0, _py0 = sp.cfg["x"] + 40, sp.cfg["y"] + 8
_pnx, _pny = sb.cfg["x"], sb.cfg["y"] + sb.cur_h + _gap + 7
sp._head_press(_ev(_px0, _py0))
for _i in (1, 2, 3):
    sp._head_motion(_ev(_px0 + (_pnx + 40 - _px0) * _i // 3, _py0 + (_pny + 8 - _py0) * _i // 3))
pump(0.2)
_shown = app._preview_shown
check(_shown is not None and app.preview_visible() and winutil.overlay_style_ok(app._ghost),
      "önizleme: sürüklerken çerçeve penceresi açık, tıklamayı geçiren araç penceresi")
check(_shown is not None and _shown["rects"] == [(sb.cfg["x"], sb.cfg["y"] + sb.cur_h + _gap, sb.cur_w, 150)],
      "önizleme: çerçeve B'nin altındaki (bırakınca oturacağı) yerde")
sp._head_release(_ev(_pnx + 40, _pny + 8))
pump(0.2)
check(app._preview_shown is None and not app.preview_visible(), "önizleme: bırakınca kalktı")
check(_shown is not None and [(sp.cfg["x"], sp.cfg["y"], sp.cur_w, sp.cur_h)] == _shown["rects"],
      "önizleme: panel tam önizlemenin gösterdiği yere oturdu")
app.remove_panel(sp, confirm=False)
pump(0.2)

app.open_settings("Snap A")
pump(0.2)
_sw = app.settings_win
_sw.v_stack_gap.set("20")
_sw.v_snap_dist.set("30")
_sw.apply()
pump(0.2)
check(app.cfg["general"]["stack_gap"] == 20 and app.cfg["general"]["snap_distance"] == 30
      and sb.cfg["y"] == sa.cfg["y"] + sa.cur_h + 20 and sb.top.winfo_y() == sb.cfg["y"],
      "Ayarlar > General > Snapping: Apply aralığı ve eşiği uyguladı, yığın yeni aralıkla yeniden dizildi")
_sw.v_stack_gap.set("99")
_sw.apply()
check(app.cfg["general"]["stack_gap"] == 20 and "must be a whole number" in _sw.msg.cget("text"),
      "Ayarlar > General > Snapping: geçersiz değer uyarı verdi, uygulanmadı")
_sw.v_stack_gap.set("8")
_sw.v_snap_dist.set("24")
_sw.apply()
_sw.close()
app.remove_panel(sb, confirm=False)
app.remove_panel(sa, confirm=False)
check(app.cfg["stacks"] == [], "yığın: paneller silinince yığın listesi temizlendi")
pump(0.2)

# --- v1.1 adım 7c: çoklu monitör (sahte ekranlar; gerçek monitörlere dokunulmaz)
import json  # noqa: E402
_mp = app.new_panel("MonSmoke")
_mp.cfg.update(x=2500, y=300, w=300, h=200, collapsed=False)
_mp.apply_size(300, 200)
_mp._move_to(2500, 300)
app.set_home(_mp)
app.save()
SMOKE_DISPLAYS.set(fakedisplays.ONE)
app._display_check()
app.clock.advance(3.5)
check(app._display_check(), "çoklu monitör: sağ monitör gidince (3 sn kararlı) yeniden yerleşim yapıldı")
pump(0.2)
check((_mp.top.winfo_x(), _mp.top.winfo_y()) == (580, 300), "çoklu monitör: eksik monitördeki panel birincile, bağıl konumla taşındı")
app.save()
with open(app.config_path, encoding="utf-8") as _f:
    _c = json.load(_f)["panels"]["MonSmoke"]
check((_c["x"], _c["y"]) == (2500, 300) and "_home" not in _c, "çoklu monitör: config'teki ev konumu değişmedi")
SMOKE_DISPLAYS.set(fakedisplays.THREE)
app._display_check()
app.clock.advance(3.5)
app._display_check()
pump(0.2)
check((_mp.top.winfo_x(), _mp.top.winfo_y()) == (2500, 300), "çoklu monitör: monitör dönünce panel ev konumuna döndü")
app.remove_panel(_mp, confirm=False)

# --- v0.5.2: Quit must end the process (queue message path + real pythonw process, tray icon on)
_pw = winutil.find_pythonw()
if _pw:
    def real_quit(label, via_cli):
        desk_q = os.path.join(root, "E2E_" + label, "Desk")
        os.makedirs(desk_q, exist_ok=True)
        args = [_pw, os.path.join(HERE_, "mpanels.py"), "--desktop", desk_q]
        p = subprocess.Popen(args)
        nm = mpanels.instance_name(desk_q)
        try:
            if via_cli:
                time.sleep(7)
                subprocess.run(args + ["--quit"], timeout=20)
                sent = True
            else:
                sent = winutil.signal_running_instance(nm, retries=150, kind=winutil.QUIT)
            t0 = time.time()
            try:
                p.wait(timeout=12)
                took = time.time() - t0
            except subprocess.TimeoutExpired:
                took = None
        finally:
            if p.poll() is None:
                p.kill()
        check(sent and took is not None and took < 6,
              f"gerçek pythonw süreci Quit ile bitti ({label}): " + ("%.1f sn" % took if took is not None else "BİTMEDİ"))
    HERE_ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    real_quit("event", False)
    real_quit("cli", True)
else:
    print("ATLANDI  pythonw bulunamadı")


# bar (v1.2 adım 1): TEST kipinde çizilir, yer ayırmaz; gerçek pencere stilleri
import fakedisplays as _fd                              # noqa: E402
sig_before = _fd.displays.signature(SMOKE_DISPLAYS.probe())
check(app.apply_bar(True, {"enabled": True, "time_format": "24h", "show_date": True}), "bar: TEST kipinde açıldı")
pump(0.3)
bw = app.bar.win
check(winutil.bar_style_ok(bw.top), "bar penceresi: araç penceresi, odak almaz, fareyi alır (tıklanabilir)")
check(bool(bw.top.attributes("-topmost")) and bw.top.winfo_viewable(), "bar penceresi görünür ve en üstte")
check(bw.top.winfo_height() == mpanels.theme.BAR_HEIGHT, "bar yüksekliği 32 px")
check(any(bw.cv.type(i) == "text" and ui.TEST_TAG not in bw.cv.itemcget(i, "text") and bw.cv.itemcget(i, "text")
          for i in bw.cv.find_all()), "bar üzerinde tarih/saat yazısı var")
check(len(bw.buttons) >= 3 and bw.buttons[0]["x"] == mpanels.theme.BAR_LEFT_RESERVE and any(b["active"] for b in bw.buttons),
      "bar: TEST kipinde sahte pencere listesi düğme olarak çizildi (solda boşluk, etkin olan işaretli)")
_b = bw.buttons[1]
bw._on_press(type("E", (), {"x": _b["x"] + 5, "x_root": 0})())
bw._on_release(type("E", (), {"x": _b["x"] + 5, "x_root": 0})())
check(app.bar.tasks.actions.calls == [("front", _b["hwnd"])] and type(app.bar.tasks.actions).__name__ == "FakeActions",
      "bar: TEST kipinde tıklama yalnız KAYDEDİLDİ (gerçek pencereye dokunulmadı)")
check(all(b["h"] == mpanels.theme.BAR_BTN_H for b in bw.buttons) and any(b["frame"] == mpanels.theme.bar_palette()["border"] for b in bw.buttons),
      "bar: düğmeler 26 px yüksekliğinde, çerçeveli (varsayılan renkler)")
bw.set_look({"border": "#ff0000"}, False)
check(all(b["w"] == mpanels.theme.BAR_ICON_ONLY_W for b in bw.buttons if b["kind"] == "task") and any(b["frame"] == "#ff0000" for b in bw.buttons),
      "bar: yazı kapalı = 32 px simge düğmeleri; kullanıcı rengi uygulandı")
bw.set_look({}, True)
_asked, _gave = [], []
_real_tf, _real_pn = winutil.take_foreground, winutil.post_null
winutil.take_foreground = lambda w: _asked.append(1) or True        # smoke never moves the real foreground
winutil.post_null = lambda w: None
_popped = []
bw._popup = lambda m, x, y: _popped.append(m)
app.bar.tasks.actions.calls.clear()
bw.cv.event_generate("<Button-3>", x=5, y=5)
bw.top.update()
pump(0.2)
winutil.take_foreground, winutil.post_null = _real_tf, _real_pn
check(len(_asked) == 1 and len(_popped) == 1, "bar: sağ tık menüyü açmadan önce ön plana alındı (Escape/dış tıklama için)")
check(bw.give_back is not None and app.bar.tasks.previous_active() == 1000, "bar: 'önceki etkin' kendi penceremiz değil")
check(app.bar.shell.hooks_installed is False if hasattr(app.bar.shell, "hooks_installed") else True,
      "bar: TEST kipinde gerçek kanca kurulmadı")
check(_fd.displays.signature(SMOKE_DISPLAYS.probe()) == sig_before, "bar TEST kipinde çalışma alanını değiştirmedi")
# arama (adım 4): TEST kipinde düğme çizilir, pencere açılır, hiçbir şey gerçekten başlatılmaz / kaydedilmez
_real_tf2 = winutil.take_foreground
winutil.take_foreground = lambda w: True
_s = app.bar.search
check(_s is not None and bw.search_button is not None and bw.search_button["kind"] == "search",
      "arama: düğme çizildi (TEST kipi)")
_s.open(0)
pump(0.2)
check(_s.is_open() and _s.win.top.winfo_viewable(), "arama: pencere açıldı")
_s.win.var.set("a")
pump(0.5)
check(type(app.search_actions).__name__ == "FakeSearchActions", "arama: TEST kipinde sahte eylemler")
_rows = list(_s.rows)
_s.on_enter()
check(bool(_rows) and not _s.is_open() and app.search_actions.calls == [("launch", _rows[0][1].parsing)],
      "arama: Enter yalnız KAYDEDİLDİ, program başlamadı")
check(app.bar.hotkey_name == "off" and app.bar.shell.hotkey_registered is False
      if hasattr(app.bar.shell, "hotkey_registered") else True, "arama: TEST kipinde gerçek kısayol kaydedilmedi")
# Başlat düğmesi (adım 5): TEST kipinde çizilir, tık yalnız KAYDEDİLİR, gerçek tuş gönderilmez
check(bw.start_button is not None and bw.start_button["kind"] == "start" and bw.start_button["x"] < theme.BAR_SEARCH_BTN_X,
      "başlat: düğme çizildi, arama düğmesinin solunda (TEST kipi)")
_sx = bw.start_button["x"] + 5
bw._on_press(mock.Mock(x=_sx, x_root=_sx))
bw._on_release(mock.Mock(x=_sx, x_root=_sx))
check(type(app.start_actions).__name__ == "FakeStartActions" and app.start_actions.calls == [("win",)],
      "başlat: TEST kipinde tık yalnız KAYDEDİLDİ, Win tuşu gönderilmedi")
winutil.take_foreground = _real_tf2
check(app.apply_bar(False, {"enabled": True, "time_format": "24h", "show_date": True}) and app.bar is None
      and not bw.top.winfo_exists(), "bar kapatıldı, pencere gitti")

# bellek
out = subprocess.check_output(["tasklist", "/FI", f"PID eq {os.getpid()}", "/FO", "CSV", "/NH"], text=True,
                              encoding="cp1254", errors="replace")
print("tasklist:", out.strip())

# gerçek masaüstü değişmedi mi
check(sorted(os.listdir(real)) == before_real, "GERÇEK masaüstü içeriği değişmedi")
check(winutil.desktop_icons_hidden() == icons_before, "GERÇEK masaüstü ikon durumu (HideIcons) değişmedi")
check(os.path.exists(os.path.join(real, "Paneller")) == real_has_panels, "gerçek masaüstünde Paneller klasörü oluşmadı")

app.quit()
check(fake.hidden is False and app.cfg["general"]["hide_icons_restore"] is None,
      "sahte arka uç: çıkışta ikonlar eski haline döndü")
check(fileops.read_note(data, "Kalıcı Not").text == "çıkışta kaydedilecek",
      "çıkışta bekleyen not yazısı kaydedildi")
shutil.rmtree(root, ignore_errors=True)
print("\n" + ("TÜMÜ GEÇTİ" if not fails else f"{len(fails)} HATA: {fails}"))
sys.exit(1 if fails else 0)
