import re,sys
def load(fn,name="const uint8_t font_16x32_compressed[]"):
    t=open(fn,encoding="latin-1").read()
    i=t.index(name); j=t.index("};",i)
    body=re.sub(r"//[^\n]*","",t[t.index("{",i)+1:j])
    return bytes(int(x,0) for x in re.findall(r"0x[0-9a-fA-F]+|\b\d+\b",body))
def glyph(font,code):
    off=code-font[2]; p=8; 
    for _ in range(off): p+=font[p]*2+1
    n=font[p]; d=bytearray(); q=p+1
    for _ in range(n):
        d+=bytes([font[q]])*(font[q+1]+1); q+=2
    d=d.ljust(64,b"\0")
    rows=[]
    for y in range(32):
        rows.append("".join("#" if (d[x+(y//8)*16]>>(y%8))&1 else "." for x in range(16)))
    return rows
if __name__=="__main__":
    f=load(sys.argv[1])
    print(len(f), f[2],f[3])
    for c in map(lambda s:int(s,0),sys.argv[2:]):
        print(hex(c)); print("\n".join(glyph(f,c)))
