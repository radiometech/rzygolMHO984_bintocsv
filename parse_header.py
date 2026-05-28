import struct, os, sys

# fix dla polskiej konsoli
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

path = r"J:\RigolDS1.bin"
file_size = os.path.getsize(path)

with open(path, "rb") as f:
    raw = f.read(min(file_size, 4096))
    f.seek(-32, 2)
    tail = f.read(32)

print(f"Plik  : {path}  ({file_size:,} B = {file_size/1e6:.3f} MB)")

# global header
num_ch = struct.unpack_from("<I", raw, 0x0C)[0]
ch_hdr = struct.unpack_from("<I", raw, 0x10)[0]
sr     = struct.unpack_from("<Q", raw, 0x1C)[0]
print(f"Magic : {raw[0:4]}")
print(f"Kanaly: {num_ch}  |  ch_hdr_size: {ch_hdr} B  |  SR: {sr:,} Sa/s ({sr/1e6:.3f} MSa/s)")
print(f"Data  : {raw[0x48:0x60].decode('ascii','replace').rstrip(chr(0))}")
print(f"Model : {raw[0x68:0x80].decode('ascii','replace').rstrip(chr(0))}")

data_start = 0x80 + num_ch * ch_hdr
print(f"\nOczekiwany poczatek danych: 0x{data_start:X} = {data_start} B")
data_bytes = file_size - data_start
print(f"Bytes danych  : {data_bytes:,}")
print(f"Jako float32  : {data_bytes/4:,.0f} probek (wszystkie kanaly)")

print(f"\n{'='*60}")
print(f"HEX DUMP naglowkow kanalow (0x80 - 0x{data_start:X})")
print(f"{'='*60}")
for i in range(0x80, data_start, 16):
    h = " ".join(f"{b:02x}" for b in raw[i:i+16])
    a = "".join(chr(b) if 32<=b<127 else "." for b in raw[i:i+16])
    marker = ""
    for c in range(num_ch):
        if i == 0x80 + c * ch_hdr:
            marker = f"  <-- CH{c+1} header"
    print(f"  {i:04x}  {h:<48}  {a}{marker}")

print(f"\n{'='*60}")
print(f"NAGLOWKI KANALOW - pola")
print(f"{'='*60}")
for c in range(num_ch):
    base = 0x80 + c * ch_hdr
    name     = raw[base:base+8].decode("ascii","replace").rstrip("\x00").strip()
    enabled  = raw[base + 0x20]
    bps      = raw[base + 0x22]
    n_samp_a = struct.unpack_from("<I", raw, base + 0x24)[0]
    n_samp_b = struct.unpack_from("<Q", raw, base + 0x24)[0]
    print(f"\n  CH{c+1} base=0x{base:X}  name={name!r}  enabled={enabled}  bps={bps}")
    print(f"       n_samp @ +0x24 uint32={n_samp_a:,}  uint64={n_samp_b:,}")
    # szukaj float64 ktore wygladaja jak napiecie
    for off in range(0, ch_hdr - 7, 8):
        v = struct.unpack_from("<d", raw, base + off)[0]
        if 0.0001 < abs(v) < 1000 and v == v:
            print(f"       float64 @ +0x{off:02X} = {v:.6g}")

print(f"\n{'='*60}")
print(f"PIERWSZE PROBKI od 0x{data_start:X}")
print(f"{'='*60}")
floats = struct.unpack_from("<16f", raw, data_start)
print(f"  float32: {[f'{v:.5f}' for v in floats]}")

print(f"\nOSTATNIE 32 B pliku:")
h = " ".join(f"{b:02x}" for b in tail)
print(f"  {h}")
last_f = struct.unpack_from("<8f", tail)
print(f"  float32: {[f'{v:.5f}' for v in last_f]}")

# oblicz rozne mozliwe podzialy
print(f"\n{'='*60}")
print(f"MOZLIWE PODZIALY DANYCH")
total_f32 = data_bytes // 4
for n in range(1, 5):
    if data_bytes % (4 * n) == 0:
        print(f"  {n} kanal(y): {total_f32//n:,} probek kazdy  ({total_f32//n/sr:.4f} s @ {sr/1e6} MSa/s)")
# tez sprawdz czy data_bytes jest dokladnie n*sr
for n in range(1, 5):
    if (data_bytes / 4) % n == 0:
        samp_per_ch = int(data_bytes / 4 / n)
        print(f"  {n} kanal(y): {samp_per_ch:,} probek = {samp_per_ch/sr:.4f} s")
