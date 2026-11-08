# מקרים ותגובות לתפעול שרת WILD

המסמך כולל פקודות ל־PowerShell במחשב המקומי ופקודות להרצה בשרת לאחר התחברות ב־SSH. שירות ה־Backend נקרא `wild.service`.

## התחברות לשרת ב־SSH מ־Windows

פתח PowerShell במחשב שלך והתחבר באמצעות מפתח SSH:

```powershell
ssh root@2.24.59.90
```

אם המפתח הפרטי אינו בנתיב ברירת המחדל, ציין את הנתיב למפתח הפרטי שלך:

```powershell
ssh -i "$env:USERPROFILE\.ssh\id_ed25519" root@2.24.59.90
```

אם שם הקובץ של המפתח שונה, החלף את `id_ed25519` בשם הקובץ המתאים. באימות הראשון, בדוק את טביעת המפתח של השרת מול המידע ב־Hostinger לפני אישור החיבור. אין להעתיק או לשלוח את קובץ המפתח הפרטי.

## שמירת שינויים ב־Git

הרץ את הפקודות ב־PowerShell במחשב שבו נמצא המאגר, ולא בחיבור SSH לשרת:

```powershell
Set-Location C:\Data\2026\wild
git status --short
git add -u
git commit -m "Describe the changes"
```

`git add -u` מוסיף שינויים ומחיקות של קבצים שכבר במעקב, אך לא קבצים חדשים. בדוק את `git status` לפני הוספת קבצים חדשים, ואל תוסיף סודות, מפתחות או קובצי recovery.

## העברת שינויים לשרת

הרץ את פקודות הבנייה וההעתקה ב־PowerShell המקומי, מתוך המאגר. נדרש מפתח SSH שמורשה להתחבר לשרת.

**בניית הפרונט והעתקתו** (נדרש כשיש שינויי Frontend):

```powershell
Set-Location C:\Data\2026\wild\frontend
npm.cmd run build
Set-Location C:\Data\2026\wild
scp.exe -r .\frontend\dist\assets root@2.24.59.90:/var/www/wild/
scp.exe .\frontend\dist\index.html root@2.24.59.90:/var/www/wild/index.html
```

**העתקת קובצי Backend ששונו** (העתק רק קבצים שהשתנו):

```powershell
Set-Location C:\Data\2026\wild
scp.exe .\backend\app\services\detect.py root@2.24.59.90:/opt/wild/app/backend/app/services/detect.py
scp.exe .\backend\app\data\species_he.json root@2.24.59.90:/opt/wild/app/backend/app/data/species_he.json
```

אחרי שינויי Backend, אתחל את השירות ובדוק שהוא פעיל:

```powershell
ssh.exe root@2.24.59.90 "systemctl restart wild.service; systemctl --no-pager status wild.service"
```

שינויי Frontend סטטיים אינם דורשים אתחול שירות; רענן את האתר בכוח (`Ctrl+F5`). אחרי פריסת שינוי בזיהוי תמונות, הרץ זיהוי מחדש על תמונה שכבר עובדה כדי להחליף תוצאות ישנות. אם SSH או SCP מחזירים `Permission denied`, יש להסדיר הרשאה למפתח הציבורי; אין לשלוח מפתח פרטי או סיסמה.

## עצירה, הפעלה ואתחול של השירות

**לעצור את השירות:**

```bash
sudo systemctl stop wild.service
```

**להפעיל את השירות:**

```bash
sudo systemctl start wild.service
```

**לאתחל את השירות:**

```bash
sudo systemctl restart wild.service
```

**לבדוק את מצב השירות:**

```bash
sudo systemctl status wild.service
```

לאחר הפעלה, חפש במצב השירות `active (running)`. עצירה או אתחול בזמן זיהוי או רינדור עלולים לקטוע את העבודה, לכן מומלץ להמתין לסיום עיבוד פעיל אם אפשר.

## השירות לא עולה או שהאתר לא מגיב

בדוק את 50 הודעות היומן האחרונות:

```bash
sudo journalctl -u wild.service -n 50 --no-pager
```

אם צריך לראות הודעות חדשות בזמן אמת:

```bash
sudo journalctl -u wild.service -f
```

אחרי בדיקת היומן, נסה להפעיל מחדש את השירות ובדוק שוב את הסטטוס. אל תעתיק למסמכים או לשיחות סיסמאות, hash של Basic Auth, תוכן של `.env` או מפתח SSH פרטי.
