"""Calendar files (R7a): one screening (.ics download) and subscription feeds
that calendar apps re-check (your plans, a club's plans).

Times are written in UTC (from each theatre's city's clock), so every
calendar app shows them at the right local time wherever the theatre is;
text is escaped and long lines folded as the iCalendar standard (RFC 5545)
requires.
"""

from datetime import datetime, timedelta, timezone

def escape(text):
    return (str(text or '').replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,')
            .replace('\r\n', '\\n').replace('\n', '\\n'))


def fold(line):
    """Lines longer than 75 octets continue on the next line after a space."""
    raw = line.encode('utf-8')
    if len(raw) <= 75:
        return [line]
    out, cur = [], b''
    for ch in line:
        b = ch.encode('utf-8')
        if len(cur) + len(b) > (75 if not out else 74):
            out.append(cur.decode('utf-8'))
            cur = b''
        cur += b
    out.append(cur.decode('utf-8'))
    return [out[0]] + [' ' + x for x in out[1:]]


def _utc(dt):
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y%m%dT%H%M%SZ')


def event(uid, start, end, summary, location='', description='', url='', cancelled=False,
          updated=None, sequence=0, city=None):
    """One VEVENT. start/end are the theatre's wall-clock times, as stored;
    `city` says whose (cities.py)."""
    import places
    lines = ['BEGIN:VEVENT', f'UID:{uid}', f'DTSTAMP:{_utc(updated or datetime.now(timezone.utc))}',
             f'DTSTART:{_utc(places.to_utc(start, city))}', f'DTEND:{_utc(places.to_utc(end, city))}',
             f'SUMMARY:{escape(summary)}', f'SEQUENCE:{int(sequence)}']
    if location:
        lines.append(f'LOCATION:{escape(location)}')
    if description:
        lines.append(f'DESCRIPTION:{escape(description)}')
    if url:
        lines.append(f'URL:{url}')
    if cancelled:
        lines.append('STATUS:CANCELLED')
    lines.append('END:VEVENT')
    return lines


def calendar(events, name=None, refresh_hours=None):
    """The whole file, CRLF line endings."""
    from app import SITE_NAME
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', f'PRODID:-//{SITE_NAME}//Showtimes//EN', 'CALSCALE:GREGORIAN',
             'METHOD:PUBLISH']
    if name:
        lines.append(f'X-WR-CALNAME:{escape(name)}')
    if refresh_hours:
        lines += [f'REFRESH-INTERVAL;VALUE=DURATION:PT{refresh_hours}H', f'X-PUBLISHED-TTL:PT{refresh_hours}H']
    for ev in events:
        lines += ev
    lines.append('END:VCALENDAR')
    return '\r\n'.join(x for line in lines for x in fold(line)) + '\r\n'


def screening_times(showtime):
    """(start, end) for a screening: its end time, else runtime + 20 minutes of trailers."""
    start = showtime.start_time
    end = showtime.end_time or (start + timedelta(minutes=(showtime.movie.runtime_minutes or 120) + 20))
    return start, end
