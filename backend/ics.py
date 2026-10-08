"""Calendar files (R7a): one screening (.ics download) and subscription feeds
that calendar apps re-check (your plans, a club's plans).

Times are written in America/New_York with its time-zone rules included, so
every calendar app shows them at the right local time; text is escaped and
long lines folded as the iCalendar standard (RFC 5545) requires.
"""

from datetime import datetime, timedelta, timezone

TZID = 'America/New_York'
VTIMEZONE = """BEGIN:VTIMEZONE
TZID:America/New_York
BEGIN:DAYLIGHT
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:EDT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:EST
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
END:VTIMEZONE""".split('\n')


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


def _local(dt):
    return dt.strftime('%Y%m%dT%H%M%S')


def _utc(dt):
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y%m%dT%H%M%SZ')


def event(uid, start, end, summary, location='', description='', url='', cancelled=False,
          updated=None, sequence=0):
    """One VEVENT (start/end are naive local DC times, as stored)."""
    lines = ['BEGIN:VEVENT', f'UID:{uid}', f'DTSTAMP:{_utc(updated or datetime.now(timezone.utc))}',
             f'DTSTART;TZID={TZID}:{_local(start)}', f'DTEND;TZID={TZID}:{_local(end)}',
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
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Cinema Club DC//Showtimes//EN', 'CALSCALE:GREGORIAN',
             'METHOD:PUBLISH']
    if name:
        lines += [f'X-WR-CALNAME:{escape(name)}', f'X-WR-TIMEZONE:{TZID}']
    if refresh_hours:
        lines += [f'REFRESH-INTERVAL;VALUE=DURATION:PT{refresh_hours}H', f'X-PUBLISHED-TTL:PT{refresh_hours}H']
    lines += VTIMEZONE
    for ev in events:
        lines += ev
    lines.append('END:VCALENDAR')
    return '\r\n'.join(x for line in lines for x in fold(line)) + '\r\n'


def screening_times(showtime):
    """(start, end) for a screening: its end time, else runtime + 20 minutes of trailers."""
    start = showtime.start_time
    end = showtime.end_time or (start + timedelta(minutes=(showtime.movie.runtime_minutes or 120) + 20))
    return start, end
