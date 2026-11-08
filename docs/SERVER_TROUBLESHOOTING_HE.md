# מקרים ותגובות לתפעול שרת WILD

הפקודות מיועדות להרצה לאחר התחברות לשרת באמצעות SSH. שירות ה־Backend נקרא `wild.service`.

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
