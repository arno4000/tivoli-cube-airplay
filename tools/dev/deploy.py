#!/usr/bin/env python3
"""Silent deploy of shairport-sync + pcmplay to the stick, then start the pipeline. Plays nothing by itself."""
import hashlib,os,re,select,socket,sys,time,uuid
HOST=os.environ["TIVOLI_HOST"];D="/data/local/tmp";U="/media/usb";B=sys.argv[1]
s=socket.create_connection((HOST,23),timeout=10)
def rd(u,d):
    b=b"";e=time.time()+d
    while time.time()<e:
        r,_,_=select.select([s],[],[],0.2)
        if r:
            x=s.recv(65536)
            if not x:break
            b+=x
            if u in b:break
    return b.decode("utf-8","replace").replace("\r","")
rd(b"zz",0.8)
def run(c,d=12):
    m=uuid.uuid4().hex[:8];s.sendall((f"{c}; echo {m}E''ND;\n").encode());return rd((m+"END").encode(),d).replace(m+"END","").strip()
t0=time.time();ok=False
while time.time()-t0<60:
    if "/media/usb" in run("cat /proc/mounts"):ok=True;break
    time.sleep(3)
print("mounted",ok);
if not ok:sys.exit(1)
print(run(f"cat /proc/uptime; ls {U}")[:300].replace("\n"," "))
for l in run("ps").splitlines():
    f=l.split()
    if f and f[0]=="root" and (f[-1].endswith("shairport-sync") or f[-1].endswith("pcmplay")):
        run(f"kill {f[1]}")
time.sleep(2)
run(f"rm {D}/recv {D}/r.part");b=open(B+"/recv","rb").read();N=130
for i in range(0,len(b),N):
    q="".join("\\0%03o"%x for x in b[i:i+N]);run(f"print -n '{q}' >> {D}/r.part",10)
print(run(f"chmod 755 {D}/r.part; mv {D}/r.part {D}/recv; md5 {D}/recv")[:50],hashlib.md5(b).hexdigest())
for name,src in (("shairport-sync",B+"/dl/shairport-sync/shairport-sync"),("pcmplay",B+"/pcmplay")):
    data=open(src,"rb").read()
    run(f"{{ {D}/recv 9123 {U}/{name} > {D}/recv.out 2>&1 & }}");time.sleep(1)
    c=socket.create_connection((HOST,9123),timeout=10);c.sendall(data);c.shutdown(socket.SHUT_WR);c.close()
    for _ in range(30):
        o=run(f"cat {D}/recv.out")
        if "received" in o:break
        time.sleep(1)
    print(name,o.strip()[:30],run(f"md5 {U}/{name}")[:34],hashlib.md5(data).hexdigest()[:32])
for l in run("ps").splitlines():
    f=l.split()
    if f and f[0]=="root" and f[-1]=="spotify":print("kill spotify",f[1]);run(f"kill {f[1]}")
run("stop mdnsd");time.sleep(2)
print("listeners:",re.sub(r"\s+"," ",run("netstat | grep LISTEN"))[:400])
print(run("grep -E 'MemFree|^Cached' /proc/meminfo").replace("\n"," "))
run("route add -net 224.0.0.0 netmask 240.0.0.0 dev wlan0; echo cube > /proc/sys/kernel/hostname")
run(f"{{ {U}/shairport-sync -c {U}/sps.conf --statistics -a Cube -p 5000 -v -o stdout 2> {D}/sps.log | {U}/pcmplay 2> {D}/pcm.log & }}")
time.sleep(6)
print(run("ps | grep -E 'shairport|pcmplay'"));print("port5000:",run("netstat | grep ':5000'")[:100])
print(run("grep -E 'MemFree' /proc/meminfo"),run("cat /proc/asound/card0/pcm0p/sub0/status")[:30])
print("LOG:",run(f"cat {D}/pcm.log",8)[-300:])
s.close()
