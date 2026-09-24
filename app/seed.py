"""Seed realistic demo data. Idempotent: only seeds when DB is empty."""
import datetime, random, json, hashlib
from . import db

random.seed(42)
D = datetime.date.today()

def d(days_ago=0):
    return (D - datetime.timedelta(days=days_ago)).isoformat()

def t(days_ago=0, h=9, m=15):
    dt = datetime.datetime.combine(D - datetime.timedelta(days=days_ago), datetime.time(h, m))
    return dt.strftime("%Y-%m-%d %H:%M:%S")

NAMES = ["Budi Santoso","Siti Aminah","Agus Wijaya","Dewi Lestari","Eko Prasetyo","Rina Marlina",
 "Joko Susilo","Maya Sari","Hendra Gunawan","Fitri Handayani","Andi Kurniawan","Lina Anggraini",
 "Tono Suprapto","Wulan Ramadhan","Bagus Setiawan","Citra Ayu","Doni Firmansyah","Endah Permatasari",
 "Fajar Nugroho","Gita Puspita"]
VILLAS = ["Perum Griya Asri","Kampung Cibadak","Jl. Melati","Komplek Mekar Jaya","Kampung Sukamaju",
          "Jl. Kenanga","Perum Bukit Damai","Kampung Caringin"]
STREETS = ["A-1/3","B-2/7","C-4/1","No. 12","No. 45","Blok D No. 8","No. 21","Blok E/2"]

def seed(con):
    if con.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] > 0:
        return False
    cur = con.cursor()

    # ---- users
    users = [
        ("Super Admin","admin","admin@spb.local","admin123","superadmin"),
        ("Admin Utama","admin2","admin2@spb.local","admin123","admin"),
        ("Operator Jaringan","operator","op@spb.local","operator123","operator"),
        ("Finance Kantor","finance","finance@spb.local","finance123","finance"),
    ]
    for name,u,e,p,r in users:
        cur.execute("INSERT INTO users(name,username,email,password_hash,role,active,created_at) VALUES(?,?,?,?,?,1,?)",
                    (name,u,e,db.hash_pw(p),r,t(60)))

    # ---- packages
    pkgs = [
        ("Starter 10 Mbps",10,5,150000,"Paket hemat untuk browsing & streaming SD"),
        ("Home 20 Mbps",20,10,250000,"Paket keluarga, streaming Full HD"),
        ("Home 50 Mbps",50,20,400000,"Gaming & WFH, latensi rendah"),
        ("Premium 100 Mbps",100,50,700000,"Untuk kantor kecil / SOHO"),
        ("Hotspot Harian",10,10,10000,"Voucher hotspot 1 hari", ),
    ]
    for p in pkgs:
        cur.execute("INSERT INTO packages(name,download_mbps,upload_mbps,price,description,status) VALUES(?,?,?,?,?,'aktif')",p)

    # ---- routers
    routers = [
        ("CORE-Bandung","10.10.0.1","7.14.3","Datacenter Bandung","core-bandung","ok","127d 4:12:03",12.5,41.2),
        ("OLT-Cibaduyut","10.10.1.2","7.10","Cibaduyut","olt-cbd","ok","45d 11:02:44",33.0,58.4),
        ("Edge-Soreang","10.10.2.3","6.49.7","Soreang","edge-srg","offline","-",0,0),
    ]
    for r in routers:
        cur.execute("INSERT INTO routers(name,host,version,location,identity,status,uptime,cpu,mem,last_checked,api_mode,port) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?, 'demo', 8728)",
                    (r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[7],r[8],t(0,h=10)))

    # ---- interfaces
    ifs = [
        (1,"ether1-gateway","ether","CC:2D:E0:11:22:33",85.2,42.1,"up","Uplink ISP transit"),
        (1,"pppoe-server","pppoe","",0,0,"up","Server PPPoE pelanggan"),
        (1,"bridge-local","bridge","",0,0,"up","Bridge OLT"),
        (2,"ether1-uplink","ether","CC:2D:E0:AA:BB:01",40.1,12.3,"up","Ke CORE"),
        (2,"ether2-olt","ether","CC:2D:E0:AA:BB:02",38.7,11.9,"up","Downstream OLT"),
        (2,"wlan1-hotspot","wlan","CC:2D:E0:AA:BB:03",2.4,1.1,"up","AP Hotspot Pasar"),
        (3,"ether1-gateway","ether","CC:2D:E0:CD:EE:01",0,0,"down","Lost power?"),
    ]
    for i in ifs:
        cur.execute("INSERT INTO interfaces(router_id,name,type,mac,rx_mbps,tx_mbps,status,comment) VALUES(?,?,?,?,?,?,?,?)",i)

    # ---- customers + pppoe
    cust_ids=[]; ppp_rows=[]
    for idx, nm in enumerate(NAMES):
        cid = idx+1
        pkg = random.choice([1,1,2,2,3,4])
        router = random.choice([1,2])
        status = "aktif"
        if idx in (4,11): status="nonaktif"
        if idx == 7: status="suspend"
        code=f"CUST-{cid:04d}"
        user=f"ppp{cid:03d}"
        cur.execute("""INSERT INTO customers(code,name,phone,email,address,package_id,router_id,
            pppoe_username,install_date,billing_day,status,balance,notes,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (code,nm,f"08{random.randint(11,89)}{random.randint(1000000,9999999)}",
             f"pelanggan{cid}@example.com", f"{random.choice(VILLAS)} {random.choice(STREETS)}, Kab. Bandung",
             pkg,router,user,d(days_ago=random.randint(120,700)),random.choice([1,5,10,15,20,25]),status,0,
             "" if idx%5 else "Pelanggan prioritas, respon cepat.", t(random.randint(120,700))))
        cust_ids.append(cid)
        online = status=="aktif" and random.random()<0.75
        up = f"{random.randint(0,20)}d {random.randint(0,23)}:{random.randint(10,59)}:{random.randint(10,59)}" if online else "-"
        cur.execute("""INSERT INTO pppoe_accounts(username,password,customer_id,profile,router_id,ip_addr,status,
            online,session_uptime,bytes_rx,bytes_tx,last_seen,service) VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'PPPoE')""",
            (user,"pw"+hashlib.md5(user.encode()).hexdigest()[:6],cid,
             cur.execute("SELECT name FROM packages WHERE id=?",(pkg,)).fetchone()["name"],router,
             f"10.{20+router}.1.{10+idx}", "aktif" if status!="suspend" else "disabled",
             1 if online else 0, up,
             random.randint(10**9,9*10**9) if online else random.randint(10**7,10**8),
             random.randint(10**8,2*10**9) if online else random.randint(10**6,10**7),
             t(0,h=random.randint(6,10)) if online else t(random.randint(1,6),h=20,m=30)))
        ppp_rows.append(user)

    # ---- hotspot users / vouchers
    profiles=[("vip-harian",1,10000),("reguler-1hari",1,10000),("malam",8,5000),("mingguan",7,50000)]
    hs=[]
    for i in range(20):
        pr=profiles[i%4]
        u=f"hs{i+1:03d}"; pw=hashlib.md5(f"hotspot{i}".encode()).hexdigest()[:8]
        used = i%5==0
        cur.execute("""INSERT INTO hotspot_users(username,password,profile,valid_until,status,used,price,comment,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (u,pw,pr[0], d(-pr[1]*pr[1]) if not used else d(random.randint(1,20)),
             "aktif", 1 if used else 0, pr[2], f"Batch {d(30-i)}", t(30-i)))
        hs.append((u,pw,pr[0],pr[1],pr[2]))
    # one voucher batch record set
    for j,(u,pw,pr,days,price) in enumerate(hs[:8]):
        cur.execute("INSERT INTO vouchers(batch,username,password,profile,validity_days,price,created_at) VALUES(?,?,?,?,?,?,?)",
                    ("HS-"+d(30).replace("-",""),u,pw,pr,days,price,t(30)))

    # ---- invoices & payments
    inv_no=0; pay_no=0
    today=D
    def period_for(off):
        m=today.month-off; y=today.year
        while m<1: m+=12; y-=1
        return f"{y:04d}-{m:02d}"
    for off in (1,0):
        per=period_for(off)
        for cid in cust_ids:
            if random.random()<0.25: continue
            inv_no+=1
            price=cur.execute("SELECT p.price FROM customers c JOIN packages p ON p.id=c.package_id WHERE c.id=?",(cid,)).fetchone()["price"]
            due=d(days_ago=-(0)) # placeholder
            issue=(today.replace(day=min(1,int(per[-2:]))) if False else None)
            y,m=int(per[:4]),int(per[5:])
            import calendar
            last=calendar.monthrange(y,m)[1]
            due_date=datetime.date(y,m,min(10,last))
            status="belum_bayar"
            if off>=1:
                r=random.random()
                if r<0.7: status="lunas"
                elif r<0.85: status="lewat_jatuh_tempo"
                else: status="belum_bayar"
            else:
                status = "lunas" if random.random()<0.35 else "belum_bayar"
            num=f"INV-{per.replace('-','')}-{inv_no:03d}"
            paid = price if status=="lunas" else 0
            cur.execute("""INSERT INTO invoices(number,customer_id,period,issue_date,due_date,amount,paid_amount,status,notes)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (num,cid,per,due_date.isoformat(),due_date.isoformat(),price,paid,status,""))
            if status=="lunas":
                pay_no+=1
                method=random.choice(["Tunai","Transfer","QRIS","Transfer"])
                pref={"Tunai":"Kantor","Transfer":"BCA VA","QRIS":"Scan QR"}[method]
                cur.execute("""INSERT INTO payments(ref,invoice_id,customer_id,amount,method,date,reference,notes,user_id,confirmed)
                    VALUES(?,?,?,?,?,?,?,?,?, 'manual')""",
                    (f"PAY-{pay_no:04d}",cur.lastrowid,cid,price,method,
                     (due_date+datetime.timedelta(days=random.randint(-5,5))).isoformat(),
                     pref+f" #{pay_no:04d}","",2))
    # a draft invoice
    inv_no+=1
    cur.execute("""INSERT INTO invoices(number,customer_id,period,issue_date,due_date,amount,paid_amount,status,notes)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        (f"INV-DRAFT-{inv_no:03d}",3,period_for(0),d(0),(D+datetime.timedelta(days=10)).isoformat(),250000,0,"draft","Tagihan manual — masih konsep"))
    # sync customer balance from unpaid invoices
    cur.execute("UPDATE customers SET balance = COALESCE((SELECT SUM(amount-paid_amount) FROM invoices WHERE customer_id=customers.id AND status IN ('belum_bayar','lewat_jatuh_tempo')),0)")

    # ---- expenses
    exps=[("Bandwidth","Pembelian transit bandwidth 200Mbps Telkomsel",8500000,d(3),"Kontrak bulanan"),
      ("Listrik","Rekening listrik OLT Cibaduyut",720000,d(5),""),
      ("Listrik","Rekening listrik Datacenter",1450000,d(5),""),
      ("Operasional","Bensin & transport teknisi lapangan",350000,d(8),"2 minggu"),
      ("Peralatan","Pembelian 5 unit ONT Zhongwei",1750000,d(12),""),
      ("Peralatan","Kabel FO 6 core 500m + splitter",980000,d(15),""),
      ("Gaji","Gaji 2 teknisi lapangan",5000000,d(25)," Agustus"),
      ("Internet Cadangan","VSAT backup Soreang",1200000,d(27),"")]
    for e in exps:
        cur.execute("INSERT INTO expenses(category,description,amount,date,notes) VALUES(?,?,?,?,?)",e)

    # ---- backups
    bks=[("core-bandung-20250920.backup","RouterOS Config","CORE-Bandung","DEMO","OK"),
         ("olt-cibaduyut-20250920.backup","RouterOS Config","OLT-Cibaduyut","DEMO","OK"),
         ("spb-db-20250924.sqlite","Database","Seluruh database aplikasi","REAL","OK"),
         ("edge-soreang-20250910.backup","RouterOS Config","Edge-Soreang","DEMO","FAILED")]
    for b in bks:
        cur.execute("INSERT INTO backups(name,kind,scope,mode,status,size,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (b[0],b[1],b[2],b[3],b[4],random.randint(4000,9000),"admin",t(random.randint(1,14))))

    # ---- events
    evs=[(3,"Edge-Soreang",t(0,h=6,m=2),"alert","Router tidak merespon ping selama 5 menit — status OFFLINE"),
         (1,"CORE-Bandung",t(0,h=3,m=40),"info","Backup konfigurasi terjadwal selesai (mode DEMO)"),
         (2,"OLT-Cibaduyut",t(1,h=21,m=5),"warn","CPU tinggi 87% selama 10 menit"),
         (1,"CORE-Bandung",t(1,m=0), "info","Maintenance window selesai, semua interface up"),
         (3,"Edge-Soreang",t(2,h=15,m=30),"warn","Interface ether1-gateway flapping (3x dalam 1 jam)"),
         (2,"OLT-Cibaduyut",t(3,h=9,m=12),"info","Pelanggan baru terhubung: ppp011"),
         (1,"CORE-Bandung",t(4,h=1,m=45),"alert","Latency ke upstream naik > 120ms"),
         (2,"OLT-Cibaduyut",t(5,h=18,m=3),"info","Firmware check: versi 7.10 (terbaru 7.15.3)")]
    for e in evs:
        cur.execute("INSERT INTO events(router_id,router_name,time,type,message) VALUES(?,?,?,?,?)",e)

    # ---- templates
    tpls=[("invoice_reminder","Pengingat Tagihan",
       "Halo {nama}, tagihan {nomor} sebesar {jumlah} untuk periode {periode} jatuh tempo pada {jatuh_tempo}. Silakan lakukan pembayaran. Terima kasih."),
      ("payment_received","Pembayaran Diterima",
       "Terima kasih {nama}, pembayaran {jumlah} untuk tagihan {nomor} telah kami terima pada {tanggal}. Status: LUNAS."),
      ("customer_suspended","Pelanggan Disuspend",
       "Yth. {nama}, koneksi Anda sementara kami suspend karena tunggakan. Hubungi 0812-3456-7890 untuk reaktivasi."),
      ("router_offline","Router Offline",
       "[ALERT] Router {router} ({lokasi}) TIDAK TERHUBUNG sejak {waktu}. Cek segera!"),
      ("router_online","Router Online",
       "[INFO] Router {router} ({lokasi}) kembali ONLINE pada {waktu}.")]
    for k,n,b in tpls:
        cur.execute("INSERT INTO templates(key,name,body) VALUES(?,?,?)",(k,n,b))

    # ---- notifications log (demo sent)
    notif=[("telegram","+62 812-xxxx (CS)","Pengingat Tagihan","3 pengingat tagihan dikirim otomatis hari ini.","sent","DEMO",t(0,h=7)),
           ("email","finance@example.com","Rekap Harian","Pendapatan bulan ini tercatat di modul Keuangan.","sent","DEMO",t(0,h=6)),
           ("telegram","grup NOC","Router Offline","Edge-Soreang tidak merespon ping.","failed","DEMO",t(0,h=6,m=3))]
    for n in notif:
        cur.execute("INSERT INTO notifications(channel,to_addr,subject,body,status,mode,created_at) VALUES(?,?,?,?,?,?,?)",n)

    # ---- settings
    s={"isp_name":"SambiraNet ISP","timezone":"Asia/Jakarta","currency":"IDR","language":"id",
       "ros_default_port":"8728","ros_default_user":"api-admin","poll_interval":"60",
       "billing_day":"1","grace_period":"3","late_behavior":"suspend",
       "tg_token":"","tg_chat":"-1002233445566","tg_enabled":"1",
       "wa_enabled":"0","wa_number":"6281234567890","email_enabled":"0","smtp_host":"","smtp_user":"",
       "theme":"system","compact":"0",
       "qris_enabled":"1","qris_merchant":"SambiraNet ISP","qris_instructions":"Scan QRIS di kasir kantor, lalu konfirmasi pembayaran manual oleh staff finance.",
       "qris_image":""}
    for k,v in s.items():
        db.set_setting(cur,k,v)

    # ---- landing
    landing={"isp_name":"SambiraNet ISP","headline":"Internet Cepat & Stabil untuk Bandung Selatan",
     "description":"Kami menyediakan layanan internet rumah, PPPoE fiber optik, dan hotspot komunitas dengan dukungan teknisi lokal 24/7.",
     "logo_text":"SN","whatsapp":"6281234567890","phone":"022-8888-7777","email":"info@sambiranet.id",
     "address":"Jl. Raya Cibaduyut No. 88, Bandung, Jawa Barat","cta_text":"Pasang Sekarang",
     "hero_badge":"Fiber to the Home • 100% jaringan sendiri","show_packages":"1",
     "footer":"© 2025 SambiraNet ISP — SambiraPandoraBox Operations"}
    cur.execute("INSERT INTO landing(id,data) VALUES(1,?)",(json.dumps(landing),))

    # ---- activity
    acts=[(t(0,h=7),"system","backup.demo","Backups","Auto-backup konfigurasi router (DEMO adapter)"),
          (t(0,h=8,m=5),"operator","login","Sesi","Login dari 10.10.0.55"),
          (t(0,h=8,m=20),"admin2","payment.create","PAY-0014","Pembayaran Transfer Rp250.000 utk INV"),
          (t(1,h=9),"admin","customer.update","CUST-0008","Status diubah ke suspend (tunggakan)"),
          (t(1,h=11),"finance","invoice.create","INV-202509-029","Tagihan bulanan September"),
          (t(2,h=14),"operator","router.update","Edge-Soreang","Dicoba reconnect via API — gagal (offline)")]
    for a in acts:
        cur.execute("INSERT INTO activity_log(ts,user,action,obj,detail) VALUES(?,?,?,?,?)",a)
    con.commit()
    return True
