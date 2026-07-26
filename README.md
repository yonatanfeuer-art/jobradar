# JobRadar

אתר חינמי שמרכז משרות Sales בישראל ממקורות ATS ציבוריים.

## העלאה ל-GitHub
1. חלץ את קובץ ה-ZIP.
2. העתק את **כל התוכן שבתיקייה** אל תיקיית `jobradar` שפתחת במחשב.
3. ב-GitHub Desktop כתוב בתחתית `First version`, לחץ **Commit to main**, ואז **Push origin**.
4. באתר GitHub: היכנס ל-Repository → **Settings** → **Pages**.
5. תחת **Build and deployment**, בחר **Deploy from a branch**.
6. Branch: `main`, Folder: `/ (root)`, ואז **Save**.
7. לאחר 1–3 דקות יופיע קישור לאתר.

## הפעלת סריקה ראשונה
ב-GitHub: לשונית **Actions** → `Update jobs` → **Run workflow**.
הסריקה תרוץ גם אוטומטית פעם ביום.

## התאמת חברות
ערוך את `data/companies.json`. כרגע נתמכות Greenhouse ו-Lever.

## הערה
מופיעות כרגע 3 משרות הדגמה עד להרצת Action הראשונה. חלק מהחברות משתמשות ב-Workday או באתר קריירה סגור ולכן אינן נתמכות עדיין.
