// GENERADO por `python -m bot generar-worker` desde bot/normalizar.py: no editar a mano.
// (tests/test_worker.py falla si quedó desactualizado)

export const USADO = "\\b(USAD[OA]S?|REACONDICIONAD[OA]S?|REFURBISHED|REFURB|RENEWED|OPEN ?BOX|OUTLET|SEGUNDA MANO|EX[- ]?DEMO|B[- ]GRADE|PRE[- ]?OWNED|SECOND ?HAND|CAJA ABIERTA|REPARAD[OA]|DEMO UNIT)\\b";
export const NOTEBOOK = "\\b(NOTEBOOK|LAPTOP|PORTATIL|NETBOOK|ULTRABOOK|CHROMEBOOK)\\b";
export const PC_ARMADA = "^(PC|COMPUTADORA|EQUIPO|CPU)\\s+(GAMER|ARMAD|DE ESCRITORIO|COMPLET)|\\b(PC ARMADA|EQUIPO ARMADO|GAMING PC|GAMING DESKTOP|DESKTOP PC(?! COMPUTER| RAM| MEMORY)|PRE-?BUILT|MINI PC|ALL[- ]IN[- ]ONE PC|PC GAMER (AMD|INTEL|RYZEN|CORE))\\b";
export const TRAY = "\\b(TRAY|SIN CAJA|S/CAJA|OEM|BULK|MPK)\\b";
export const RE_NVIDIA = "\\bRTX\\s*-?\\s*(\\d{4})\\s*(TI\\s*SUPER|TI|SUPER)?(?![A-Z0-9])";
export const RE_NVIDIA_PEGADO = "\\bRTX\\s*-?\\s*(\\d{4})(TI|S)?(?=[-\\s/]|$)";
export const RE_AMD = "\\bRX\\s*-?\\s*(\\d{4})\\s*(XTX|XT|GRE)?(?![A-Z0-9])";
export const RE_VRAM = "(?<![\\dX.])(?<!\\d-)(\\d{1,2})\\s*G(?:B)?(?![A-Z0-9])";
export const RE_RYZEN = "\\bRYZEN\\s*([3579])?\\s*(?:PRO\\s*)?([789]\\d{3})\\s*(X3D2|X3D|X|F|G|GT|E)?(?![A-Z0-9])";
export const RE_RYZEN_SUELTO = "(?<![A-Z0-9])([789]\\d{3})(X3D2|X3D|X|F|G)(?![A-Z0-9])";
export const RE_ULTRA = "\\bULTRA\\s*([579])\\s*-?\\s*(2\\d{2})\\s*(KF|K|F|T)?(?:\\s*PLUS)?(?![A-Z0-9])";
export const RE_ULTRA_LEJOS = "\\bULTRA\\s*([579])\\b.{0,30}?(?<![\\d.])(2\\d{2})\\s*(KF|K|F|T)?(?![A-Z0-9.])";
export const RE_ULTRA_PLUS = "\\bULTRA\\s*[579]\\s*-?\\s*2\\d{2}\\s*(?:KF|K|F|T)?\\s*PLUS\\b";
export const RE_I14 = "\\bI([3579])\\s*-?\\s*(14\\d{2}0)\\s*(KS|KF|K|F|T)?(?![A-Z0-9])";
export const RE_CORSAIR = "\\bCM[A-Z0-9]*?(\\d{2,3})GX5M(\\d)[A-Z](\\d{4})[CZ](\\d{2})";
export const RE_GSKILL = "\\bF5-(\\d{4})[A-Z](\\d{2})\\d{2}[A-Z](\\d{2})G[A-Z]?X(\\d)";
export const RE_KINGSTON = "\\bKF5(\\d{2})C(\\d{2})[A-Z0-9]*?(?:K(\\d))?-(\\d{2,3})\\b";
export const RE_KIT = "(?<!\\d)([1-4])\\s*[X\\*]\\s*(8|16|24|32|48|64)\\s*(?:GB?)?(?![\\dA-Z])";
export const RE_KIT_INV = "(?<!\\d)(\\d{1,2})\\s*GB?\\s*[X\\*]\\s*([1-4])(?!\\d)";
export const RE_GB = "(?<![X\\*\\d])(\\d{1,3})\\s*GB\\b";
export const RE_VEL = "(?<!\\d)(\\d{4})\\s*(?:MHZ|MT/?S)";
export const RE_VEL_DDR = "DDR5[- ]?(\\d{4})(?!\\d)";
export const RE_VEL_SUELTA = "(?<!\\d)([4-9][0-9]00)(?!\\d|\\s*GB)";
export const RE_CL = "\\bCL\\s?-?(\\d{2})\\b|\\bC(\\d{2})\\b";
export const SSD_NO = "\\b(PORTABLE|PORTATIL|EXTERN[OA]|EXTERNAL|USB|ENCLOSURE|CARRY|DOCK|GABINETE|ADAPTADOR|ADAPTER|MICRO ?SD|SD CARD|MEMORY CARD|PENDRIVE|FLASH DRIVE|HDD|DISCO RIGIDO|HARD DRIVE|CADDY)\\b";
export const SSD_SI = "\\b(SSD|NVME|M\\.2|SOLIDO|SOLID STATE)\\b";
export const RE_SSD_TB = "(?<![\\d.])(\\d(?:[.,]\\d)?)\\s*TB\\b";
export const RE_SSD_GB = "(?<![\\d.])(240|250|256|480|500|512|960|1000|2000|4000)\\s*GB\\b";
export const RE_SSD_GEN = "\\b(?:PCIE|PCI-?E|GEN)\\s*(?:GEN\\s*)?([345])(?:\\.0)?(?:\\s*X4)?\\b";
export const VRAM_VALIDAS = [4, 6, 8, 10, 12, 16, 20, 24, 32];
export const VRAM_POR_DEFECTO = {"RTX 4060": 8, "RTX 4070": 12, "RTX 4070 Super": 12, "RTX 4070 Ti": 12, "RTX 4070 Ti Super": 16, "RTX 4080": 16, "RTX 4080 Super": 16, "RTX 4090": 24, "RTX 5050": 8, "RTX 5060": 8, "RTX 5070": 12, "RTX 5070 Ti": 16, "RTX 5080": 16, "RTX 5090": 32, "RX 7600": 8, "RX 7600 XT": 16, "RX 7700 XT": 12, "RX 7800 XT": 16, "RX 7900 GRE": 16, "RX 7900 XT": 20, "RX 7900 XTX": 24, "RX 9060": 8, "RX 9070 GRE": 12, "RX 9070": 16, "RX 9070 XT": 16};
export const LINEAS_SSD = [["9100 PRO", "Samsung", 5], ["990 PRO", "Samsung", 4], ["990 EVO", "Samsung", 4], ["980 PRO", "Samsung", 4], ["870 EVO", "Samsung", 0], ["SN8100", "WD", 5], ["SN850X", "WD", 4], ["SN7100", "WD", 4], ["SN770", "WD", 4], ["SN5000", "WD", 4], ["SN580", "WD", 4], ["T705", "Crucial", 5], ["T700", "Crucial", 5], ["T710", "Crucial", 5], ["T500", "Crucial", 4], ["P510", "Crucial", 5], ["P310", "Crucial", 4], ["P3 PLUS", "Crucial", 4], ["MX500", "Crucial", 0], ["KC3000", "Kingston", 4], ["FURY RENEGADE", "Kingston", 4], ["NV3", "Kingston", 4], ["NV2", "Kingston", 4], ["MP700", "Corsair", 5], ["MP600", "Corsair", 4], ["FIRECUDA 540", "Seagate", 5], ["FIRECUDA 530", "Seagate", 4], ["SX8200", "ADATA", 3], ["LEGEND 960", "ADATA", 4], ["LEGEND 900", "ADATA", 4], ["P5 PLUS", "Crucial", 4]];
