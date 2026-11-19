"""
WeDRINK Sticker Server
======================
Receives sale data from the CISePOS browser userscript and prints
one sticker per item on the Datamax E-4303 label printer.

Usage:
    python sticker_server.py

The server listens on http://localhost:9876 by default.
Configuration is in config.json (created on first run).
"""

import json
import os
import re
import sys
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("ERROR: Pillow is not installed.")
    print("Run:  pip install Pillow")
    sys.exit(1)

try:
    import win32print
    import win32ui
    from PIL import ImageWin
except ImportError:
    print("ERROR: pywin32 is not installed.")
    print("Run:  pip install pywin32")
    sys.exit(1)


# ── Paths ──────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
PROCESSED_FILE = BASE_DIR / "processed_bills.json"
LOG_FILE = BASE_DIR / "sticker_log.txt"
PREVIEW_DIR = BASE_DIR / "previews"


# ── Defaults ───────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "printer_name": "",          # Empty = auto-detect Datamax
    "listen_port": 9876,
    "label_width_mm": 38,
    "label_height_mm": 28,
    "printer_dpi": 300,          # Datamax E-4303 = 300 DPI
    "skip_items": ["straw", "cone", "cup", "spoon"],
    "brand_name": "WeDRINK",
    "show_price": True,
    "margin_px": 15,
}


# ── Config & State ─────────────────────────────────────────────
def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    # First run: create the file
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2)
    return dict(DEFAULT_CONFIG)


def load_processed():
    if PROCESSED_FILE.exists():
        with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_processed(bill_set):
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(bill_set), f)


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── Sticker Image ──────────────────────────────────────────────
def _load_font(name, size):
    """Try to load a TrueType font, fall back to default."""
    for path in [
        name,
        f"C:/Windows/Fonts/{name}",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def text_wrap(draw, text, font, max_width):
    """Word-wrap text to fit within max_width pixels."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


def create_sticker(item_name, token_no, customer_name, price, config):
    """Generate a 1-bit sticker image for the label printer."""
    dpi = config["printer_dpi"]
    margin = config["margin_px"]
    brand = config["brand_name"]

    w_px = int(config["label_width_mm"] / 25.4 * dpi)
    h_px = int(config["label_height_mm"] / 25.4 * dpi)

    img = Image.new("L", (w_px, h_px), 255)   # grayscale white
    draw = ImageDraw.Draw(img)

    usable_w = w_px - 2 * margin

    # Fonts (scaled to DPI)
    font_brand = _load_font("arial.ttf", int(dpi * 0.06))
    font_item  = _load_font("arialbd.ttf", int(dpi * 0.10))
    font_info  = _load_font("arial.ttf", int(dpi * 0.07))
    font_token = _load_font("arialbd.ttf", int(dpi * 0.08))

    y = margin

    # ── Brand name (centered) ─────────────────────────────
    bb = draw.textbbox((0, 0), brand, font=font_brand)
    tw = bb[2] - bb[0]
    draw.text(((w_px - tw) // 2, y), brand, fill=0, font=font_brand)
    y += (bb[3] - bb[1]) + 4

    # ── Separator line ────────────────────────────────────
    draw.line([(margin, y), (w_px - margin, y)], fill=0, width=2)
    y += 6

    # ── Item name (bold, word-wrapped, centered) ──────────
    item_lines = text_wrap(draw, item_name, font_item, usable_w)
    for line in item_lines[:3]:
        bb = draw.textbbox((0, 0), line, font=font_item)
        tw = bb[2] - bb[0]
        draw.text(((w_px - tw) // 2, y), line, fill=0, font=font_item)
        y += (bb[3] - bb[1]) + 2
    y += 2

    # ── Token number (centered) ───────────────────────────
    token_text = f"# {token_no}"
    bb = draw.textbbox((0, 0), token_text, font=font_token)
    tw = bb[2] - bb[0]
    draw.text(((w_px - tw) // 2, y), token_text, fill=0, font=font_token)
    y += (bb[3] - bb[1]) + 2

    # ── Customer name (centered, if present) ──────────────
    if customer_name:
        bb = draw.textbbox((0, 0), customer_name, font=font_info)
        tw = bb[2] - bb[0]
        draw.text(((w_px - tw) // 2, y), customer_name, fill=0, font=font_info)
        y += (bb[3] - bb[1]) + 2

    # ── Price (centered, if enabled) ──────────────────────
    if config.get("show_price") and price:
        price_text = f"Rs. {int(price)}"
        bb = draw.textbbox((0, 0), price_text, font=font_info)
        tw = bb[2] - bb[0]
        draw.text(((w_px - tw) // 2, y), price_text, fill=0, font=font_info)

    return img


# ── Printer ────────────────────────────────────────────────────
def find_datamax_printer():
    """Auto-detect a Datamax printer from the Windows printer list."""
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    printers = [p[2] for p in win32print.EnumPrinters(flags)]
    for name in printers:
        lower = name.lower()
        if "datamax" in lower or "e-4303" in lower or "e4303" in lower:
            return name
    return None


def list_printers():
    """Return all Windows printer names."""
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    return [p[2] for p in win32print.EnumPrinters(flags)]


def print_sticker(image, printer_name):
    """Send a PIL Image to a Windows printer via GDI."""
    hdc = win32ui.CreateDC()
    hdc.CreatePrinterDC(printer_name)

    # Query the actual printable area in pixels
    horz_res = hdc.GetDeviceCaps(8)    # HORZRES  – printable width in px
    vert_res = hdc.GetDeviceCaps(10)   # VERTRES  – printable height in px

    hdc.StartDoc("WeDRINK Sticker")
    hdc.StartPage()

    # Convert to RGB for maximum driver compatibility
    # (1-bit DIBs have palette issues on many label printer drivers)
    print_img = image.convert("RGB") if image.mode != "RGB" else image
    dib = ImageWin.Dib(print_img)

    img_w, img_h = print_img.size

    # Scale to fit the printable area, keeping aspect ratio
    scale = min(horz_res / img_w, vert_res / img_h, 1.0)
    dest_w = int(img_w * scale)
    dest_h = int(img_h * scale)

    log(f"  Print: image {img_w}x{img_h} → dest {dest_w}x{dest_h}  "
        f"(printable {horz_res}x{vert_res}, scale {scale:.2f})")

    dib.draw(hdc.GetHandleOutput(), (0, 0, dest_w, dest_h))

    hdc.EndPage()
    hdc.EndDoc()
    hdc.DeleteDC()


# ── Skip-list Check ────────────────────────────────────────────
_skip_cache = {}

def should_skip(item_name, skip_list):
    """Return True if item_name matches any skip word (whole word, case-insensitive).
    'straw' skips 'straws' but NOT 'Strawberry'."""
    key = (item_name, tuple(skip_list))
    if key in _skip_cache:
        return _skip_cache[key]
    name_lower = item_name.lower()
    for word in skip_list:
        if re.search(r"\b" + re.escape(word) + r"s?\b", name_lower):
            _skip_cache[key] = True
            return True
    _skip_cache[key] = False
    return False


# ── Sale Processing ───────────────────────────────────────────
def process_sale(data, config, processed_bills):
    """Parse a CISePOS insertSale payload and print stickers."""
    try:
        response = data.get("response", {})
        request_data = data.get("request", {})

        master = response.get("master", {})
        detail = response.get("detail", [])

        bill_no = master.get("BillNo", "")
        if not bill_no:
            log("WARNING: No BillNo in payload, skipping.")
            return {"status": "error", "reason": "no BillNo"}

        # ── Duplicate check ───────────────────────────────
        if bill_no in processed_bills:
            log(f"SKIP duplicate bill: {bill_no}")
            return {"status": "skipped", "reason": "duplicate"}

        token_no = master.get("DailyBillNo", "?")

        # Customer name: try request form data first, then response
        customer_name = request_data.get("PartyName", "").strip()
        if customer_name in ("", "undefined", "null", "None"):
            customer_name = ""

        # ── Resolve printer ───────────────────────────────
        printer_name = config.get("printer_name") or find_datamax_printer()
        if not printer_name:
            log("ERROR: Datamax printer not found! Set printer_name in config.json")
            log(f"  Available printers: {list_printers()}")
            return {"status": "error", "reason": "printer not found"}

        stickers_printed = 0
        items_skipped = 0

        for item in detail:
            item_name = item.get("ItemName") or item.get("items", {}).get("Item", "Unknown")
            quantity = int(item.get("Quantity", 1))
            rate = item.get("Rate", 0)
            try:
                rate = float(rate)
            except (ValueError, TypeError):
                rate = 0

            if should_skip(item_name, config["skip_items"]):
                items_skipped += quantity
                log(f"  SKIP item: {item_name} (matches skip list)")
                continue

            # Print one sticker per piece
            for i in range(quantity):
                img = create_sticker(
                    item_name=item_name,
                    token_no=token_no,
                    customer_name=customer_name,
                    price=rate,
                    config=config,
                )

                # Save preview image (for debugging)
                PREVIEW_DIR.mkdir(exist_ok=True)
                safe_name = re.sub(r'[\\/:*?"<>|]', '_', f"{bill_no}_{item_name[:20]}_{i+1}")
                img.save(str(PREVIEW_DIR / f"{safe_name}.png"))

                # Print
                print_sticker(img, printer_name)
                stickers_printed += 1

        # ── Mark processed ────────────────────────────────
        processed_bills.add(bill_no)
        save_processed(processed_bills)

        log(
            f"✓ Bill {bill_no} | Token {token_no} | "
            f"Customer: {customer_name or '(none)'} | "
            f"Stickers: {stickers_printed} | Skipped: {items_skipped}"
        )
        return {
            "status": "ok",
            "bill_no": bill_no,
            "token": token_no,
            "stickers_printed": stickers_printed,
            "items_skipped": items_skipped,
        }

    except Exception as e:
        log(f"ERROR: {e}\n{traceback.format_exc()}")
        return {"status": "error", "reason": str(e)}


# ── HTTP Handler ──────────────────────────────────────────────
class StickerHandler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self._cors(200)

    def do_GET(self):
        if self.path == "/status":
            printer = self.server.config.get("printer_name") or find_datamax_printer()
            body = {
                "status": "running",
                "processed_count": len(self.server.processed_bills),
                "printer": printer or "NOT FOUND",
                "available_printers": list_printers(),
            }
            self._json(200, body)
        elif self.path == "/test":
            # Print a test sticker without a real sale
            printer = self.server.config.get("printer_name") or find_datamax_printer()
            if not printer:
                self._json(500, {"status": "error", "reason": "printer not found"})
                return
            img = create_sticker("Test Sticker", "0", "Test Customer", 100, self.server.config)
            PREVIEW_DIR.mkdir(exist_ok=True)
            img.save(str(PREVIEW_DIR / "test_sticker.png"))
            try:
                print_sticker(img, printer)
                self._json(200, {"status": "ok", "message": "test sticker printed"})
            except Exception as e:
                self._json(500, {"status": "error", "reason": str(e)})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/new-sale":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self._json(400, {"status": "error", "reason": "invalid JSON"})
                return
            result = process_sale(data, self.server.config, self.server.processed_bills)
            self._json(200, result)
        elif self.path == "/reprint":
            # Remove a bill from processed list so it can be reprinted
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
                bill_no = data.get("bill_no", "")
                if bill_no in self.server.processed_bills:
                    self.server.processed_bills.discard(bill_no)
                    save_processed(self.server.processed_bills)
                    log(f"Cleared bill {bill_no} for reprint")
                    self._json(200, {"status": "ok", "message": f"bill {bill_no} cleared for reprint"})
                else:
                    self._json(200, {"status": "ok", "message": "bill was not in processed list"})
            except Exception as e:
                self._json(400, {"status": "error", "reason": str(e)})
        else:
            self._json(404, {"error": "not found"})

    # ── Helpers ───────────────────────────────────────────
    def _cors(self, code):
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json(self, code, obj):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode("utf-8"))

    def log_message(self, fmt, *args):
        pass   # silence default access log


# ── Main ──────────────────────────────────────────────────────
def main():
    config = load_config()
    processed_bills = load_processed()

    printer = config.get("printer_name") or find_datamax_printer()
    log("=" * 54)
    log("  WeDRINK Sticker Server")
    log("=" * 54)
    if printer:
        log(f"  Printer : {printer}")
    else:
        log("  Printer : NOT FOUND")
        log("  Available printers:")
        for p in list_printers():
            log(f"    - {p}")
        log("  Set printer_name in config.json or install driver.")

    port = config["listen_port"]
    log(f"  Port    : {port}")
    log(f"  Skip    : {config['skip_items']}")
    log(f"  Bills   : {len(processed_bills)} already processed")
    log("─" * 54)
    log("Waiting for sales from CISePOS browser...")
    log("")

    server = HTTPServer(("127.0.0.1", port), StickerHandler)
    server.config = config
    server.processed_bills = processed_bills

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("\nServer stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
