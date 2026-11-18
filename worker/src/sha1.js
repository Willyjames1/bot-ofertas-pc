// SHA-1 sincrónico y chico: la clave de cada publicación para el botón "❌ Sin stock" es
// sha1(link)[:16], igual que stock.clave_url() en Python. Se calcula solo para lo que se muestra
// (5 a 10 links por búsqueda), así que no hace falta crypto.subtle (que es async).
export function sha1(texto) {
  const b = new TextEncoder().encode(texto);
  const largo = b.length;
  const n = (((largo + 8) >> 6) + 1) * 16;
  const w = new Uint32Array(n);
  for (let i = 0; i < largo; i++) w[i >> 2] |= b[i] << (24 - (i % 4) * 8);
  w[largo >> 2] |= 0x80 << (24 - (largo % 4) * 8);
  w[n - 1] = largo * 8;
  let [h0, h1, h2, h3, h4] = [0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476, 0xc3d2e1f0];
  const x = new Uint32Array(80);
  const rot = (v, s) => (v << s) | (v >>> (32 - s));
  for (let i = 0; i < n; i += 16) {
    for (let t = 0; t < 16; t++) x[t] = w[i + t];
    for (let t = 16; t < 80; t++) x[t] = rot(x[t - 3] ^ x[t - 8] ^ x[t - 14] ^ x[t - 16], 1);
    let [a, bb, c, d, e] = [h0, h1, h2, h3, h4];
    for (let t = 0; t < 80; t++) {
      const f = t < 20 ? (bb & c) | (~bb & d) : t < 40 ? bb ^ c ^ d : t < 60 ? (bb & c) | (bb & d) | (c & d) : bb ^ c ^ d;
      const k = t < 20 ? 0x5a827999 : t < 40 ? 0x6ed9eba1 : t < 60 ? 0x8f1bbcdc : 0xca62c1d6;
      const tmp = (rot(a, 5) + f + e + k + x[t]) >>> 0;
      e = d; d = c; c = rot(bb, 30) >>> 0; bb = a; a = tmp;
    }
    h0 = (h0 + a) >>> 0; h1 = (h1 + bb) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0; h4 = (h4 + e) >>> 0;
  }
  return [h0, h1, h2, h3, h4].map((v) => v.toString(16).padStart(8, "0")).join("");
}

export const claveUrl = (url) => sha1(url).slice(0, 16);
