content = open('run_old.py', encoding='utf-8').read()
content = content.replace("✅ ", "")
with open('run_old.py', 'w', encoding='utf-8') as f:
    f.write(content)
