import os
import sqlite3

p = 'telegrambot.sample.db'
print('Path:', os.path.abspath(p))
print('Exists:', os.path.exists(p))
if not os.path.exists(p):
    raise SystemExit('DB not found')
print('SizeKB:', round(os.path.getsize(p)/1024,2))

con = sqlite3.connect(p)
c = con.cursor()
for t in ('users','movies_cache','user_collection'):
    try:
        c.execute(f"select count(*) from {t}")
        print(f"{t}:", c.fetchone()[0])
    except Exception as e:
        print(f"{t}: error -", e)

print('\nUsers sample:')
for row in c.execute('select id,telegram_id,username,genre from users'):
    print(row)

print('\nMovies sample:')
for row in c.execute('select id,tmdb_id,title_en,genres from movies_cache'):
    print(row)

con.close()
