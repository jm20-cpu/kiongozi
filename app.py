from flask import Flask, render_template, request, jsonify, redirect, url_for
import sqlite3, requests, re, os
from bs4 import BeautifulSoup
from datetime import datetime

app=Flask(__name__)
DATABASE="kiongozi.db"
PARLIAMENT_URL="https://www.parliament.go.ke/the-national-assembly/mps"
COUNTIES=["Baringo","Bomet","Bungoma","Busia","Elgeyo-Marakwet","Embu","Garissa","Homa Bay","Isiolo","Kajiado","Kakamega","Kericho","Kiambu","Kilifi","Kirinyaga","Kisii","Kisumu","Kitui","Kwale","Laikipia","Lamu","Machakos","Makueni","Mandera","Marsabit","Meru","Migori","Mombasa","Murang'a","Nairobi","Nakuru","Nandi","Narok","Nyamira","Nyandarua","Nyeri","Samburu","Siaya","Taita-Taveta","Tana River","Tharaka-Nithi","Trans Nzoia","Turkana","Uasin Gishu","Vihiga","Wajir","West Pokot"]
POSITIONS=["President","Governor","Senator","Woman Representative","Member of National Assembly","MCA"]
WEIGHTS={"Legislative Performance":20,"Attendance & Participation":15,"Representation":15,"Development & Projects":15,"Financial Accountability":15,"Promises & Commitments":10,"Transparency":10}

def db():
    c=sqlite3.connect(DATABASE); c.row_factory=sqlite3.Row; return c

def init_db():
    c=db()
    c.execute("""CREATE TABLE IF NOT EXISTS leaders(
    id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,position TEXT NOT NULL,
    county TEXT,constituency TEXT,ward TEXT,party TEXT,status TEXT,bio TEXT,
    photo_url TEXT,source_url TEXT,source_name TEXT,source_updated TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS evaluations(
    id INTEGER PRIMARY KEY AUTOINCREMENT,leader_id INTEGER UNIQUE,legislative REAL,
    attendance REAL,representation REAL,development REAL,finance REAL,promises REAL,
    transparency REAL,overall REAL,evidence_status TEXT,updated_at TEXT,
    FOREIGN KEY(leader_id) REFERENCES leaders(id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS evidence(
    id INTEGER PRIMARY KEY AUTOINCREMENT,leader_id INTEGER,category TEXT,title TEXT,
    description TEXT,source TEXT,source_url TEXT,verified INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(leader_id) REFERENCES leaders(id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS updates(
    id INTEGER PRIMARY KEY AUTOINCREMENT,message TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    c.commit(); c.close()

def overall(v):
    vals=[(v[k],WEIGHTS[k]) for k in WEIGHTS if v.get(k) is not None]
    return round(sum(x*w for x,w in vals)/sum(w for _,w in vals),1) if vals else None

def _clean_name(value):
    value=re.sub(r"\s+"," ",value or "").strip()
    value=re.sub(r"^(RT\.\s*HON\.?|HON\.?)\s*", "", value, flags=re.I)
    value=re.sub(r"^\(([^)]*)\)\s*", "", value)
    return value.strip(" .,")

def _parse_parliament_page(html):
    soup=BeautifulSoup(html,"html.parser")
    records=[]
    for table in soup.find_all("table"):
        header_cells=table.find_all("th")
        headers=[x.get_text(" ",strip=True).lower() for x in header_cells]
        if not headers or "member of parliament" not in " ".join(headers):
            continue
        index={}
        for i,h in enumerate(headers):
            if "member of parliament" in h: index["name"]=i
            elif h=="county" or "county" in h: index["county"]=i
            elif "constituency" in h: index["constituency"]=i
            elif h=="party" or "party" in h: index["party"]=i
            elif "status" in h: index["status"]=i

        for row in table.find_all("tr"):
            cells=[x.get_text(" ",strip=True) for x in row.find_all("td")]
            if not cells or "name" not in index or index["name"] >= len(cells):
                continue
            raw_name=cells[index["name"]]
            upper=raw_name.upper()
            if not raw_name or "HON" not in upper or upper.strip()=="VACANT":
                continue
            name=_clean_name(raw_name)
            if not name:
                continue
            def cell(key):
                i=index.get(key)
                return cells[i].strip() if i is not None and i < len(cells) else ""
            records.append({
                "name":name,
                "county":cell("county"),
                "constituency":cell("constituency"),
                "party":cell("party"),
                "status":cell("status") or "Listed"
            })
    return records

def import_parliament():
    """Import National Assembly records from Parliament's paginated directory.

    This importer is deliberately defensive: the Parliament site paginates the
    member table, and the Render/Gunicorn process does not execute app.py as
    __main__. V2 therefore imports on application startup when the database is
    empty and also supports a manual refresh.
    """
    total=0
    seen=set()
    c=db()
    try:
        # Parliament currently exposes roughly 35 pages of member records.
        # We stop after several consecutive pages with no records.
        empty_pages=0
        for page in range(0, 45):
            urls=[
                f"{PARLIAMENT_URL}?field_parliament_value=2022&page={page}",
                f"https://www.parliament.go.ke/index.php/the-national-assembly/mps?field_parliament_value=2022&page={page}"
            ]
            records=[]
            last_error=None
            for url in urls:
                try:
                    r=requests.get(
                        url, timeout=12,
                        headers={
                            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36",
                            "Accept":"text/html,application/xhtml+xml"
                        }
                    )
                    r.raise_for_status()
                    records=_parse_parliament_page(r.text)
                    if records:
                        break
                except Exception as e:
                    last_error=e

            if not records:
                empty_pages += 1
                if empty_pages >= 3:
                    break
                continue
            empty_pages=0

            for rec in records:
                key=(rec["name"].lower(), rec["constituency"].lower())
                if key in seen:
                    continue
                seen.add(key)
                exists=c.execute(
                    """SELECT id FROM leaders
                       WHERE LOWER(name)=LOWER(?) AND position=?
                       AND IFNULL(constituency,'')=?""",
                    (rec["name"],"Member of National Assembly",rec["constituency"])
                ).fetchone()
                if exists:
                    continue

                cur=c.execute(
                    """INSERT INTO leaders
                    (name,position,county,constituency,party,status,
                     source_url,source_name,source_updated)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        rec["name"],"Member of National Assembly",
                        rec["county"],rec["constituency"],rec["party"],
                        rec["status"],PARLIAMENT_URL,"Parliament of Kenya",
                        datetime.now().strftime("%Y-%m-%d")
                    )
                )
                lid=cur.lastrowid
                c.execute(
                    """INSERT INTO evidence
                    (leader_id,category,title,description,source,source_url,verified)
                    VALUES(?,?,?,?,?,?,1)""",
                    (
                        lid,"Official Identity","Official Parliament Member Record",
                        "Identity and constituency information imported from the official Parliament of Kenya members directory.",
                        "Parliament of Kenya",PARLIAMENT_URL
                    )
                )
                total += 1

        c.execute(
            "INSERT INTO updates(message) VALUES(?)",
            (f"Imported {total} new National Assembly records from Parliament of Kenya.",)
        )
        c.commit()
        return total
    except Exception as e:
        c.rollback()
        print("Import error:", repr(e))
        return total
    finally:
        c.close()

@app.route("/")
def index():
    c=db()
    total=c.execute("SELECT COUNT(*) FROM leaders").fetchone()[0]
    evaluated=c.execute("SELECT COUNT(*) FROM evaluations WHERE overall IS NOT NULL").fetchone()[0]
    counties=c.execute("SELECT COUNT(DISTINCT county) FROM leaders WHERE county IS NOT NULL AND county!=''").fetchone()[0]
    positions=c.execute("SELECT COUNT(DISTINCT position) FROM leaders").fetchone()[0]
    top=c.execute("""SELECT l.*,e.overall FROM leaders l LEFT JOIN evaluations e ON l.id=e.leader_id WHERE e.overall IS NOT NULL ORDER BY e.overall DESC LIMIT 5""").fetchall(); c.close()
    recent=c.execute("SELECT message,created_at FROM updates ORDER BY id DESC LIMIT 5").fetchall() if False else []
    return render_template("index.html",total=total,evaluated=evaluated,counties=counties,positions=positions,top=top)

@app.route("/leaders")
def leaders():
    search=request.args.get("search","").strip(); county=request.args.get("county",""); position=request.args.get("position","")
    q="SELECT l.*,e.overall FROM leaders l LEFT JOIN evaluations e ON l.id=e.leader_id WHERE 1=1"; p=[]
    if search:
        q+=" AND (l.name LIKE ? OR l.constituency LIKE ? OR l.ward LIKE ? OR l.party LIKE ?)"
        p += [f"%{search}%"]*4
    if county: q+=" AND l.county=?"; p.append(county)
    if position: q+=" AND l.position=?"; p.append(position)
    q+=" ORDER BY CASE WHEN e.overall IS NULL THEN 1 ELSE 0 END,e.overall DESC,l.name"
    c=db(); rows=c.execute(q,p).fetchall(); c.close()
    return render_template("leaders.html",leaders=rows,counties=COUNTIES,positions=POSITIONS,search=search,selected_county=county,selected_position=position)

@app.route("/leader/<int:leader_id>")
def leader(leader_id):
    c=db(); l=c.execute("""SELECT l.*,e.legislative,e.attendance,e.representation,e.development,e.finance,e.promises,e.transparency,e.overall,e.evidence_status,e.updated_at FROM leaders l LEFT JOIN evaluations e ON l.id=e.leader_id WHERE l.id=?""",(leader_id,)).fetchone()
    if not l: c.close(); return "Leader not found",404
    ev=c.execute("SELECT * FROM evidence WHERE leader_id=? ORDER BY created_at DESC",(leader_id,)).fetchall(); c.close()
    return render_template("leader.html",leader=l,evidence=ev,weights=WEIGHTS)

@app.route("/evaluate/<int:leader_id>",methods=["GET","POST"])
def evaluate(leader_id):
    c=db(); l=c.execute("SELECT * FROM leaders WHERE id=?",(leader_id,)).fetchone()
    if not l: c.close(); return "Leader not found",404
    if request.method=="POST":
        def val(x):
            try:
                s=request.form.get(x,"").strip()
                return None if s=="" else max(0,min(100,float(s)))
            except: return None
        v={"Legislative Performance":val("legislative"),"Attendance & Participation":val("attendance"),"Representation":val("representation"),"Development & Projects":val("development"),"Financial Accountability":val("finance"),"Promises & Commitments":val("promises"),"Transparency":val("transparency")}
        values=[v[k] for k in v]; score=overall(v)
        if c.execute("SELECT id FROM evaluations WHERE leader_id=?",(leader_id,)).fetchone():
            c.execute("""UPDATE evaluations SET legislative=?,attendance=?,representation=?,development=?,finance=?,promises=?,transparency=?,overall=?,evidence_status=?,updated_at=? WHERE leader_id=?""",values+[score,"Manually verified evaluation",datetime.now().strftime("%Y-%m-%d %H:%M"),leader_id])
        else:
            c.execute("""INSERT INTO evaluations(leader_id,legislative,attendance,representation,development,finance,promises,transparency,overall,evidence_status,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",[leader_id]+values+[score,"Manually verified evaluation",datetime.now().strftime("%Y-%m-%d %H:%M")])
        c.commit(); c.close(); return redirect(url_for("leader",leader_id=leader_id))
    e=c.execute("SELECT * FROM evaluations WHERE leader_id=?",(leader_id,)).fetchone(); c.close()
    return render_template("evaluate.html",leader=l,evaluation=e,weights=WEIGHTS)

@app.route("/statistics")
def statistics():
    c=db()
    total=c.execute("SELECT COUNT(*) FROM leaders").fetchone()[0]
    evaluated=c.execute("SELECT COUNT(*) FROM evaluations WHERE overall IS NOT NULL").fetchone()[0]
    avg=c.execute("SELECT ROUND(AVG(overall),1) FROM evaluations WHERE overall IS NOT NULL").fetchone()[0]
    evidence=c.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    verified=c.execute("SELECT COUNT(*) FROM evidence WHERE verified=1").fetchone()[0]
    by_position=c.execute("SELECT l.position,COUNT(*) total,ROUND(AVG(e.overall),1) avg FROM leaders l LEFT JOIN evaluations e ON l.id=e.leader_id GROUP BY l.position ORDER BY total DESC").fetchall()
    by_county=c.execute("SELECT l.county,COUNT(*) total,COUNT(e.overall) evaluated,ROUND(AVG(e.overall),1) avg FROM leaders l LEFT JOIN evaluations e ON l.id=e.leader_id WHERE l.county IS NOT NULL AND l.county!='' GROUP BY l.county ORDER BY avg DESC, l.county").fetchall()
    categories=[]
    for col,label in [("legislative","Legislative Performance"),("attendance","Attendance & Participation"),("representation","Representation"),("development","Development & Projects"),("finance","Financial Accountability"),("promises","Promises & Commitments"),("transparency","Transparency")]:
        row=c.execute(f"SELECT ROUND(AVG({col}),1),COUNT({col}) FROM evaluations WHERE {col} IS NOT NULL").fetchone()
        categories.append({"name":label,"avg":row[0],"count":row[1]})
    parties=c.execute("SELECT COALESCE(NULLIF(party,''),'Independent/Not stated') party,COUNT(*) total FROM leaders GROUP BY party ORDER BY total DESC LIMIT 12").fetchall()
    top=c.execute("SELECT l.*,e.overall FROM leaders l JOIN evaluations e ON l.id=e.leader_id WHERE e.overall IS NOT NULL ORDER BY e.overall DESC,l.name LIMIT 10").fetchall()
    c.close()
    return render_template("statistics.html",total=total,evaluated=evaluated,avg=avg,evidence=evidence,verified=verified,by_position=by_position,by_county=by_county,categories=categories,parties=parties,top=top)

@app.route("/api/statistics")
def api_statistics():
    c=db(); data={
      "leaders":c.execute("SELECT COUNT(*) FROM leaders").fetchone()[0],
      "evaluated":c.execute("SELECT COUNT(*) FROM evaluations WHERE overall IS NOT NULL").fetchone()[0],
      "average":c.execute("SELECT ROUND(AVG(overall),1) FROM evaluations WHERE overall IS NOT NULL").fetchone()[0],
      "evidence":c.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    }; c.close(); return jsonify(data)

@app.route("/counties")
def counties():
    c=db(); data=[]
    for x in COUNTIES:
        total=c.execute("SELECT COUNT(*) FROM leaders WHERE county=?",(x,)).fetchone()[0]
        ev=c.execute("SELECT COUNT(*) FROM leaders l JOIN evaluations e ON l.id=e.leader_id WHERE l.county=? AND e.overall IS NOT NULL",(x,)).fetchone()[0]
        data.append({"name":x,"leaders":total,"evaluated":ev})
    c.close(); return render_template("counties.html",counties=data)

@app.route("/positions")
def positions():
    c=db(); data=[{"name":p,"count":c.execute("SELECT COUNT(*) FROM leaders WHERE position=?",(p,)).fetchone()[0]} for p in POSITIONS]; c.close()
    return render_template("positions.html",positions=data)

@app.route("/compare")
def compare():
    ids=request.args.getlist("id"); c=db(); rows=[]
    if ids:
        ph=",".join("?" for _ in ids)
        rows=c.execute(f"SELECT l.*,e.legislative,e.attendance,e.representation,e.development,e.finance,e.promises,e.transparency,e.overall FROM leaders l LEFT JOIN evaluations e ON l.id=e.leader_id WHERE l.id IN ({ph})",ids).fetchall()
    all_leaders=c.execute("SELECT id,name,position,county FROM leaders ORDER BY name").fetchall(); c.close()
    return render_template("compare.html",leaders=rows,all_leaders=all_leaders)

@app.route("/aspirants")
def aspirants():
    c=db(); rows=c.execute("SELECT * FROM leaders WHERE LOWER(status) LIKE '%aspirant%' OR LOWER(status) LIKE '%candidate%' ORDER BY name").fetchall(); c.close()
    return render_template("aspirants.html",leaders=rows)

@app.route("/refresh")
def refresh(): return render_template("refresh.html",count=import_parliament())
@app.route("/api/refresh")
def api_refresh(): return jsonify({"success":True,"imported":import_parliament()})
@app.route("/api/leaders")
def api_leaders():
    c=db(); rows=c.execute("""SELECT l.*,e.legislative,e.attendance,e.representation,e.development,e.finance,e.promises,e.transparency,e.overall FROM leaders l LEFT JOIN evaluations e ON l.id=e.leader_id ORDER BY l.name""").fetchall(); c.close()
    return jsonify([dict(x) for x in rows])
@app.route("/health")
def health():
    c=db()
    count=c.execute("SELECT COUNT(*) FROM leaders").fetchone()[0]
    c.close()
    return jsonify({
        "status":"healthy",
        "application":"Kiongozi",
        "leaders":count,
        "time":datetime.now().isoformat()
    })

init_db()

# IMPORTANT: Gunicorn imports this module instead of executing it as __main__.
# V2 therefore performs the first data import during application initialization.
try:
    c=db()
    leader_count=c.execute("SELECT COUNT(*) FROM leaders").fetchone()[0]
    c.close()
    if leader_count == 0:
        import_parliament()
except Exception as startup_error:
    print("Startup import warning:", repr(startup_error))

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)),debug=True)
