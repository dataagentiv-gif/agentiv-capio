from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.enums import TA_CENTER
from pathlib import Path

out = Path("output/pdf/capio-brief-pengenalan-1.6.0.pdf")
out.parent.mkdir(parents=True, exist_ok=True)
doc = SimpleDocTemplate(str(out), pagesize=A4, rightMargin=18*mm, leftMargin=18*mm, topMargin=16*mm, bottomMargin=16*mm)
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="TitleBlue", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=25, leading=30, textColor=colors.HexColor("#123B8C"), alignment=TA_CENTER, spaceAfter=8))
styles.add(ParagraphStyle(name="Sub", parent=styles["Normal"], fontSize=11, leading=16, textColor=colors.HexColor("#53627A"), alignment=TA_CENTER, spaceAfter=16))
styles.add(ParagraphStyle(name="H2Blue", parent=styles["Heading2"], fontSize=15, leading=19, textColor=colors.HexColor("#123B8C"), spaceBefore=10, spaceAfter=7))
styles.add(ParagraphStyle(name="BodyClean", parent=styles["BodyText"], fontSize=10.5, leading=15, spaceAfter=6))
styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=9, leading=13, textColor=colors.HexColor("#53627A")))
styles.add(ParagraphStyle(name="Quote", parent=styles["BodyText"], fontSize=11, leading=16, leftIndent=12, rightIndent=12, textColor=colors.HexColor("#123B8C"), backColor=colors.HexColor("#EEF3FB"), borderPadding=10, spaceBefore=4, spaceAfter=10))

def p(text, style="BodyClean"):
    return Paragraph(text, styles[style])

story = [
    p("CAPIO", "TitleBlue"),
    p("Brief Video Pengenalan untuk Channel Pribadi + Kolaborasi Agentiv", "Sub"),
    p("Versi produk: 1.6.0 &nbsp;|&nbsp; Durasi target: 5-7 menit", "Small"),
    Spacer(1, 8),
    p("Tujuan video", "H2Blue"),
    p("Kenalkan CAPIO sebagai video clipping engine self-hosted yang membantu mengubah video panjang menjadi klip pendek siap posting. Video ini bukan tutorial lengkap; fokusnya adalah menjelaskan masalah, solusi, perbedaan Template dan Custom, serta pengalaman memakai CAPIO."),
    p("Hook pembuka", "H2Blue"),
    p("Kalau lu punya video panjang tapi males motong satu-satu jadi short, CAPIO bisa otomatis nyari momen terbaik dan bikin jadi klip siap posting.", "Quote"),
    p("Alur video yang disarankan", "H2Blue"),
]
rows = [
    ["00:00-00:20", "Hook", "Tampilkan video panjang lalu potongan hasil klip secara cepat."],
    ["00:20-01:00", "Masalah", "Jelaskan waktu editing, mencari momen, caption manual, dan format vertikal."],
    ["01:00-02:00", "Kenalan CAPIO", "Self-hosted, BYOK Gemini, pemrosesan lokal, hasil tersimpan di komputer."],
    ["02:00-03:30", "Demo flow", "Input video, pilih mode, preview, Proses, lalu Hasil."],
    ["03:30-04:30", "Template vs Custom", "Bandingkan template siap pakai dengan kontrol Custom."],
    ["04:30-05:15", "Siapa yang cocok", "Podcaster, kreator edukasi, agensi, social media manager, pemilik channel."],
    ["05:15-06:00", "Kebutuhan", "Docker, Gemini API key, resource laptop, dan komputer tetap menyala saat job."],
    ["06:00-06:30", "CTA", "Arahkan ke halaman CAPIO dan video tutorial lengkap di channel pribadi."],
]
t = Table(rows, colWidths=[27*mm, 32*mm, 112*mm], repeatRows=1)
t.setStyle(TableStyle([
    ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#123B8C")), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
    ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTNAME", (0,1), (-1,-1), "Helvetica"),
    ("FONTSIZE", (0,0), (-1,-1), 8.8), ("LEADING", (0,0), (-1,-1), 12),
    ("GRID", (0,0), (-1,-1), .35, colors.HexColor("#CBD5E1")), ("VALIGN", (0,0), (-1,-1), "TOP"),
    ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F6F8FC")]), ("TOPPADDING", (0,0), (-1,-1), 7), ("BOTTOMPADDING", (0,0), (-1,-1), 7),
]))
story += [t, PageBreak(), p("Poin yang wajib ditunjukkan", "H2Blue")]
for title, body in [
    ("Masalah yang diselesaikan", "Motong video panjang makan waktu, mencari momen menarik sulit, caption manual melelahkan, dan format video sering tidak sesuai platform."),
    ("CAPIO itu apa", "CAPIO berjalan di komputer sendiri, memakai API key Gemini milik pengguna, dan menyimpan source/hasil di storage lokal."),
    ("Template", "Tampilan siap pakai dengan karakter visual dan adjustment yang sudah dibatasi agar hasil konsisten."),
    ("Custom", "Pengguna memilih rasio, komposisi video, crop atau contain, latar, caption, dan hook dalam satu konfigurasi job."),
    ("Demo hasil", "Tampilkan 3-5 contoh: full screen, pembicara di samping, kotak tengah, blur atas-bawah, dan satu Custom."),
    ("Batasan yang jujur", "CAPIO perlu Docker dan Gemini API key. Lama proses bergantung pada durasi source dan antrean. CAPIO bukan editor video manual penuh."),
]:
    story += [p(title, "H2Blue"), p(body)]
story += [p("Contoh penutup", "H2Blue"), p("Kalau lu sering punya video panjang dan ingin mengubahnya jadi banyak konten pendek tanpa editing manual berulang, CAPIO bisa jadi workflow yang cocok. Link informasi dan instalasinya gue taruh di deskripsi.", "Quote")]
story += [p("Strategi kolaborasi channel", "H2Blue")]
collab = [["Channel pribadi", "Pengalaman, demo, opini, tutorial penggunaan, dan contoh workflow nyata."], ["Channel Agentiv", "Versi resmi, update produk, instalasi, changelog, dan support."], ["Kolaborator", "Gunakan fitur Collaborator agar video muncul di dua channel. Samakan thumbnail, judul, CTA, dan link silang di deskripsi serta pinned comment."]]
ct = Table(collab, colWidths=[38*mm, 133*mm])
ct.setStyle(TableStyle([("BACKGROUND", (0,0), (0,-1), colors.HexColor("#EEF3FB")), ("GRID", (0,0), (-1,-1), .35, colors.HexColor("#CBD5E1")), ("VALIGN", (0,0), (-1,-1), "TOP"), ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,-1), 9.5), ("LEADING", (0,0), (-1,-1), 13), ("TOPPADDING", (0,0), (-1,-1), 8), ("BOTTOMPADDING", (0,0), (-1,-1), 8)]))
story += [ct, Spacer(1, 12), p("Catatan produksi: gunakan screen recording singkat untuk UI; jangan menjadikan video ini tutorial instalasi. Tutorial instalasi, update, dan multi-worker tetap berada di dokumentasi Agentiv.", "Small")]

def footer(canvas, doc):
    canvas.saveState(); canvas.setFont("Helvetica", 8); canvas.setFillColor(colors.HexColor("#718096")); canvas.drawString(18*mm, 9*mm, "CAPIO - Brief Pengenalan v1.6.0"); canvas.drawRightString(192*mm, 9*mm, f"Halaman {doc.page}"); canvas.restoreState()

doc.build(story, onFirstPage=footer, onLaterPages=footer)
print(out.resolve())
