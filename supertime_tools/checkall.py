import sys, os
from lvflat import read_datalog_header, decode_dt4
td,_ = read_datalog_header(sys.argv[1])
ok=bad=0; fails=[]
for root,_,files in os.walk(sys.argv[2]):
    for f in files:
        if f.lower().endswith(('.dt4','.dt3')):
            p=os.path.join(root,f)
            try:
                d,u,s = decode_dt4(p,td)
                if u==s: ok+=1
                else: bad+=1; fails.append((p,'consumed %d of %d'%(u,s)))
            except Exception as e:
                bad+=1; fails.append((p,repr(e)[:80]))
print("ok",ok,"bad",bad)
for p,m in fails[:40]: print(" ",p.replace(sys.argv[2],''),m)
