"""Transactional raw journal and reversible JSON/CSV delivery."""
import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.ingestion.common import dumps

# Sources exported together: any job in a group regenerates every file of that
# group, so a Google-only run still rewrites app_store.* as before.
SOURCE_GROUPS = (('google_play', 'app_store'), ('tiki',), ('shopee',))


def job_key(job):
    return dumps([job['source'], job['app_id'], job['country'], job['language']])


def export_sources(keys):
    used = {json.loads(key)[0] for key in keys}
    return [source for group in SOURCE_GROUPS if used.intersection(group) for source in group]


def review_key(event):
    raw, source = event['review'], event['source_domain']
    if source == 'google_play':
        value = raw.get('reviewId')
    elif source == 'app_store':
        value = raw.get('id', {}).get('label')
    elif source == 'tiki':
        value = raw.get('id')
    elif source == 'shopee':
        value = raw.get('cmtid')
    else:
        value = None
    if value:
        return str(value)
    # Stable fallback only for retry bookkeeping; never modify the payload.
    return 'sha256:' + hashlib.sha256(dumps(raw).encode('utf-8')).hexdigest()


class Dataset:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.folder / 'checkpoint.sqlite3')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS jobs (
                job_key TEXT PRIMARY KEY, state TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reviews (
                job_key TEXT NOT NULL, review_key TEXT NOT NULL,
                source TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(job_key, review_key)
            );
        ''')

    def close(self):
        self.db.close()

    def count(self, key):
        return self.db.execute('SELECT COUNT(*) FROM reviews WHERE job_key=?', (key,)).fetchone()[0]

    def state(self, key):
        row = self.db.execute('SELECT state FROM jobs WHERE job_key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else {'cursor': {}, 'pending': [], 'exhausted': False}

    def save_page(self, key, rows, cursor, exhausted, target):
        """Persist accepted reviews and the cursor in the same transaction.

        Retain unused page rows in pending so a later quota increase loses nothing.
        """
        count = self.count(key)
        pending = []
        with self.db:
            for event in rows:
                if count >= target:
                    pending.append(event)
                    continue
                result = self.db.execute(
                    'INSERT OR IGNORE INTO reviews VALUES (?, ?, ?, ?)',
                    (key, review_key(event), event['source_domain'], dumps(event)),
                )
                count += result.rowcount
            state = {'cursor': cursor, 'pending': pending, 'exhausted': exhausted}
            self.db.execute('INSERT OR REPLACE INTO jobs VALUES (?, ?)', (key, dumps(state)))
        return count

    def reset_cursor(self, key):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO jobs VALUES (?, ?)',
                            (key, dumps({'cursor': {}, 'pending': [], 'exhausted': False})))

    def export(self, keys):
        """Stream only jobs in this run; stage each file before replacing it."""
        keys = list(keys)
        self.db.execute('CREATE TEMP TABLE IF NOT EXISTS export_jobs (job_key TEXT PRIMARY KEY)')
        self.db.execute('DELETE FROM export_jobs')
        self.db.executemany('INSERT INTO export_jobs VALUES (?)', ((key,) for key in keys))
        self.db.commit()
        outputs = {}
        for source in export_sources(keys):
            paths = {ext: self.folder / f'{source}.{ext}' for ext in ('json', 'jsonl', 'csv')}
            temps = {ext: path.with_suffix(path.suffix + '.tmp') for ext, path in paths.items()}
            fields = ['source_domain', 'item_id', 'country', 'language', 'collected_at',
                      'review_id', 'review_text', 'rating', 'review_time', 'app_json', 'review_json']
            count = 0
            with temps['json'].open('w', encoding='utf-8') as array, \
                    temps['jsonl'].open('w', encoding='utf-8') as lines, \
                    temps['csv'].open('w', encoding='utf-8-sig', newline='') as table:
                writer = csv.DictWriter(table, fieldnames=fields)
                writer.writeheader()
                array.write('[\n')
                query = '''SELECT payload FROM reviews JOIN export_jobs USING(job_key)
                           WHERE source=? ORDER BY reviews.rowid'''
                for (payload,) in self.db.execute(query, (source,)):
                    event = json.loads(payload)
                    array.write((' ,\n' if count else '') + payload)
                    lines.write(payload + '\n')
                    writer.writerow(csv_row(event))
                    count += 1
                array.write('\n]\n')
            for ext, path in paths.items():
                temps[ext].replace(path)
            outputs[source] = {'count': count, 'files': {ext: str(path) for ext, path in paths.items()}}
        return outputs


def epoch_iso(value):
    """Display Unix seconds as ISO 8601 UTC; leave any other value unchanged."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value, timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            pass
    return value


def csv_row(event):
    raw = event['review']
    if event['source_domain'] == 'google_play':
        text, rating, when = raw.get('content'), raw.get('score'), raw.get('at')
    elif event['source_domain'] == 'tiki':
        # Tiki titles are star-rating templates ("Cực kì hài lòng"); content is the user's text.
        text, rating, when = raw.get('content'), raw.get('rating'), epoch_iso(raw.get('created_at'))
    elif event['source_domain'] == 'shopee':
        text, rating, when = raw.get('comment'), raw.get('rating_star'), epoch_iso(raw.get('ctime'))
    else:
        text = raw.get('content', {}).get('label')
        rating = raw.get('im:rating', {}).get('label')
        when = raw.get('updated', {}).get('label')
    row = {name: event.get(name) for name in
           ('source_domain', 'item_id', 'country', 'language', 'collected_at')}
    row.update(review_id=review_key(event), review_text=text, rating=rating, review_time=when)
    # Protect spreadsheet display columns. Exact originals remain in the JSON columns.
    for name, value in row.items():
        if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
            row[name] = "'" + value
    row['app_json'] = dumps(event['app'])
    row['review_json'] = dumps(raw)
    return row
