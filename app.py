import os
import sys
import sqlite3
import pgeocode
from flask import Flask, render_template, request, redirect, url_for
from geopy.distance import geodesic
from werkzeug.utils import secure_filename
import openpyxl
import webbrowser
import threading

# ✅ PyInstaller 兼容模板路径
base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
template_folder = os.path.join(base_path, "templates")
app = Flask(__name__, template_folder=template_folder)

if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.abspath(".")

db_path = os.path.join(base_path, 'store_data.db')

nomi = pgeocode.Nominatim('us')

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def get_all_stores():
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, owner, address, zip_code, price, open_status, lat, lon FROM stores")
    stores = cur.fetchall()
    conn.close()
    return stores

def get_store_by_id(store_id):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, owner, address, zip_code, price, open_status FROM stores WHERE id = ?", (store_id,))
    store = cur.fetchone()
    conn.close()
    return store

def get_nearest_stores(user_zip, top_n=3):
    user_location = nomi.query_postal_code(user_zip)
    if user_location is None or user_location.latitude is None:
        return []
    user_coord = (user_location.latitude, user_location.longitude)
    stores = get_all_stores()
    nearby = []
    for store in stores:
        store_coord = (store[6], store[7])
        try:
            distance_km = geodesic(user_coord, store_coord).km
            nearby.append((store, distance_km))
        except:
            continue
    nearby.sort(key=lambda x: x[1])
    return nearby[:top_n]

@app.route("/", methods=["GET", "POST"])
def index():
    results = []
    user_zip = ""
    if request.method == "POST":
        user_zip = request.form.get("zip_code")
        results = get_nearest_stores(user_zip)
    return render_template("index.html", results=results, user_zip=user_zip)

@app.route("/admin", methods=["GET", "POST"])
def admin():
    address_kw = request.form.get("address_kw", "").strip()
    zip_code = request.form.get("zip_code", "").strip()
    owner_kw = request.form.get("owner_kw", "").strip()

    query = "SELECT id, owner, address, zip_code, price, open_status, lat, lon FROM stores WHERE 1=1"
    params = []

    if address_kw:
        query += " AND address LIKE ?"
        params.append(f"%{address_kw}%")
    if zip_code:
        query += " AND zip_code = ?"
        params.append(zip_code)
    if owner_kw:
        query += " AND owner LIKE ?"
        params.append(f"%{owner_kw}%")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(query, params)
    stores = cur.fetchall()
    conn.close()

    return render_template("admin.html", stores=stores,
                           address_kw=address_kw, zip_code=zip_code, owner_kw=owner_kw)


@app.route("/add", methods=["GET", "POST"])
def add_store():
    if request.method == "POST":
        owner = request.form["owner"]
        address = request.form["address"]
        zip_code = request.form["zip_code"]
        price = request.form["price"]
        open_status = 1 if request.form.get("open_status") == "on" else 0
        location = nomi.query_postal_code(zip_code)
        lat, lon = location.latitude, location.longitude
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("INSERT INTO stores (owner, address, zip_code, price, open_status, lat, lon) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (owner, address, zip_code, price, open_status, lat, lon))
        conn.commit()
        conn.close()
        return redirect(url_for("admin"))
    return render_template("add_store.html")

@app.route("/edit/<int:store_id>", methods=["GET", "POST"])
def edit_store(store_id):
    store = get_store_by_id(store_id)
    if request.method == "POST":
        owner = request.form["owner"]
        address = request.form["address"]
        zip_code = request.form["zip_code"]
        price = request.form["price"]
        open_status = 1 if request.form.get("open_status") == "on" else 0
        location = nomi.query_postal_code(zip_code)
        lat, lon = location.latitude, location.longitude
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            UPDATE stores SET owner=?, address=?, zip_code=?, price=?, open_status=?, lat=?, lon=?
            WHERE id=?
        """, (owner, address, zip_code, price, open_status, lat, lon, store_id))
        conn.commit()
        conn.close()
        return redirect(url_for("admin"))
    return render_template("edit_store.html", store=store)

@app.route("/delete/<int:store_id>")
def delete_store(store_id):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM stores WHERE id = ?", (store_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))

@app.route("/import", methods=["POST"])
def import_stores():
    file = request.files.get("file")
    if not file:
        return "未选择文件", 400
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    if filename.endswith(".txt"):
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) != 5:
                    continue
                owner, address, zip_code, price, open_status = parts
                location = nomi.query_postal_code(zip_code)
                lat, lon = location.latitude, location.longitude
                cur.execute("INSERT INTO stores (owner, address, zip_code, price, open_status, lat, lon) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (owner, address, zip_code, price, int(open_status), lat, lon))
    elif filename.endswith(".xlsx"):
        wb = openpyxl.load_workbook(filepath)
        sheet = wb.active
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if len(row) < 5:
                continue
            owner, address, zip_code, price, open_status = row
            location = nomi.query_postal_code(str(zip_code))
            lat, lon = location.latitude, location.longitude
            cur.execute("INSERT INTO stores (owner, address, zip_code, price, open_status, lat, lon) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (owner, address, str(zip_code), str(price), int(open_status), lat, lon))
    conn.commit()
    conn.close()
    os.remove(filepath)
    return redirect(url_for("admin"))

# ✅ 自动打开浏览器
def open_browser():
    webbrowser.open("http://127.0.0.1:5000")

if __name__ == '__main__':
    threading.Timer(1.0, open_browser).start()
    app.run(debug=False)

