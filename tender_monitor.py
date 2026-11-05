"""
LSGD Kerala tender monitor - puthiya tender notices mathram kandupidikkum.

Engane work cheyyunnu:
  * District page edukkum (POST), table parse cheyyum
  * Oro notice-inteyum "window number" (eg. G286117/2026) seen.json-il ullathumayi compare cheyyum
  * Puthiyathu mathram print cheyyum, new_tenders.txt-il ezhuthum, Telegram settings undenkil ayakkum

Settings (environment variables):
  DISTRICTS   comma separated district codes, default: Kasargode, Kannur, Wayanad, Kozhikode,
              Malappuram, Palakkad, Thrissur  ("14.0,13.0,12.0,11.0,10.0,9.0,8.0")
  LAST_WINDOW (optional) ningal ormikkunna avasaanathe window number, eg. G286117/2026 allenkil 286117.
              Ithu koduthaal athinu shesham ullathu (number valuthu) mathram kaanikkum.
  MAX_PAGES   oru districtil ethra page vare nokkanam (default 5)
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   (optional)
"""
import json, os, sys, time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://tender.lsgkerala.gov.in/pages/displayTender.php"
SEEN_FILE = Path(__file__).with_name("seen.json")
OUT_FILE = Path(__file__).with_name("new_tenders.txt")
DISTRICT_NAMES = {"1.0": "Thiruvananthapuram", "2.0": "Kollam", "3.0": "Pathanamthitta",
                  "4.0": "Alappuzha", "5.0": "Kottayam", "6.0": "Idukki", "7.0": "Ernakulam",
                  "8.0": "Thrissur", "9.0": "Palakkad", "10.0": "Malappuram", "11.0": "Kozhikode",
                  "12.0": "Wayanad", "13.0": "Kannur", "14.0": "Kasargode"}
DEFAULT_DISTRICTS = "14.0,13.0,12.0,11.0,10.0,9.0,8.0"
HEADERS = {"User-Agent": "Mozilla/5.0 (personal tender checker; once a day)"}


def win_num(window_no):
    """'G286117/2026' -> 286117"""
    m = __import__("re").search(r"(\d+)", str(window_no))
    return int(m.group(1)) if m else 0


def parse_page(html, page_url=BASE):
    """Return (list of tender dicts, next_page_url or None)."""
    soup = BeautifulSoup(html, "html.parser")
    tenders = []
    for tr in soup.select("tr.clsLBContent, tr.clsLBContentLT"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        link = tds[2].find("a")
        window_no = tds[2].get_text(strip=True)          # eg. G286117/2026
        tenders.append({
            "window_no": window_no,
            "localbody": tds[0].get_text(" ", strip=True).replace("\xa0", " "),
            "tender_no": tds[1].get_text(strip=True),
            "subject": tds[3].get_text(" ", strip=True),
            "last_date": tds[4].get_text(strip=True),
            "pdf": urljoin(page_url, link["href"]) if link else "",
        })
    nxt = None
    img = soup.find("img", alt="Next Page")
    if img and img.parent and img.parent.name == "a":
        nxt = urljoin(page_url, img.parent["href"])
    return tenders, nxt


def fetch_district(session, dist, max_pages):
    data = {"nameDist": dist, "distid": dist, "namelbtype": "0", "namelocalbody": "0",
            "txtsearch": "", "localbodyid": "", "s": "0", "sbmtsearch": "Search"}
    r = session.post(BASE, data=data, headers=HEADERS, timeout=60)
    r.raise_for_status()
    results, nxt = parse_page(r.text)
    pages = 1
    while nxt and pages < max_pages:
        time.sleep(2)                                    # site-ine load kodukkaruthu
        r = session.get(nxt, headers=HEADERS, timeout=60)
        r.raise_for_status()
        more, nxt = parse_page(r.text, nxt)
        if not more:
            break
        results += more
        pages += 1
    return results


def send_telegram(text):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    for i in range(0, len(text), 3800):
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": text[i:i + 3800],
                            "disable_web_page_preview": "true"}, timeout=30)


def main():
    districts = [d.strip() for d in os.getenv("DISTRICTS", DEFAULT_DISTRICTS).split(",") if d.strip()]
    max_pages = int(os.getenv("MAX_PAGES", "5"))
    last_window = os.getenv("LAST_WINDOW", "").strip()
    threshold = win_num(last_window) if last_window else None

    seen = set(json.loads(SEEN_FILE.read_text())) if SEEN_FILE.exists() else None
    first_run = seen is None
    seen = seen or set()

    session = requests.Session()
    all_found = []
    for d in districts:
        found = fetch_district(session, d, max_pages)
        for t in found:
            t["district"] = DISTRICT_NAMES.get(d, d)
            all_found.append(t)
        nums = [win_num(t["window_no"]) for t in found]
        print(f"{DISTRICT_NAMES.get(d, d)}: {len(found)} notices kitti (ettavum valuthu window number: {max(nums) if nums else '-'})")
        time.sleep(2)
    print(f"Ake {len(all_found)} notices kitti.\n")
    if not all_found:
        print("WARNING: ONNUM KITTIYILLA - site block cheythathaakam allenkil page maariyathaakam.")
        sys.exit(1)

    if threshold:
        new = [t for t in all_found if win_num(t["window_no"]) > threshold]
    elif first_run:
        new = []
    else:
        new = [t for t in all_found if t["window_no"] not in seen]

    seen.update(t["window_no"] for t in all_found)
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=0))

    if first_run and not threshold:
        print(f"First run: {len(all_found)} notices note cheythu. Ini mudal puthiyathu mathram kaanikkum.")
        return
    if not new:
        print("Puthiya tender illa.")
        OUT_FILE.write_text("")
        return

    new.sort(key=lambda t: (t["district"], -win_num(t["window_no"])))
    lines = [f"{len(new)} puthiya tender:\n"]
    current = None
    for t in new:
        if t["district"] != current:
            current = t["district"]
            lines.append(f"=== {current} ===\n")
        lines.append(f"{t['localbody']}\n{t['subject']}\nWindow: {t['window_no']} | Last date: {t['last_date']}\n{t['pdf']}\n")
    text = "\n".join(lines)
    print(text)
    OUT_FILE.write_text(text)
    send_telegram(text)


if __name__ == "__main__":
    main()
