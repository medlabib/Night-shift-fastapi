"""Server-side translations for PDFs and validation messages.

The frontend has its own catalog; this one covers what the server renders
or generates — the print layouts and the messages the API sends back.

Dates are formatted here rather than by strftime, because strftime is
locale-dependent on the host and would need system locales installed. The
month and day names below make the output identical everywhere.
"""

from __future__ import annotations

import datetime as dt

SUPPORTED = ("en", "fr", "ar")
RTL = {"ar"}

MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"],
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin",
           "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
    "ar": ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
           "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"],
}

# Monday first, matching datetime.weekday().
WEEKDAYS = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "fr": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
    "ar": ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"],
}

WEEKDAYS_SHORT = {
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "fr": ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"],
    "ar": ["إثن", "ثلا", "أرب", "خمي", "جمع", "سبت", "أحد"],
}

CATALOG = {
    "en": {
        "pdf.night": "Night",
        "pdf.date": "Date",
        "pdf.day": "Day",
        "pdf.points": "Pts",
        "pdf.onCall": "On call",
        "pdf.nobody": "— nobody on call —",
        "pdf.holidayShort": "hol",
        "pdf.on": "On",
        "pdf.shifts": "Shifts",
        "pdf.pointsFull": "Points",
        "pdf.workload": "Workload",
        "pdf.doctor": "Doctor",
        "pdf.grade": "Grade",
        "pdf.weekend": "Weekend",
        "pdf.holiday": "Holiday",
        "pdf.none": "none",
        "pdf.meta": "{nights} nights · {shifts} shifts",
        "pdf.balance": "balance {value}%",
        "pdf.generated": "generated {date}",
        "pdf.period": "{start} to {end}",
        "pdf.legendWeekend": "Weekend",
        "pdf.legendHoliday": "Public holiday",
        "pdf.legendWeights": "Weights: weekday 1.0 · Saturday 1.5 · Sunday and holidays 2.0",
        "pdf.page": "Page {page} of {pages}",
        "pdf.shortTitle": "{count} nights not fully covered",
        "pdf.shortOne": "1 night not fully covered",
        "status.draft": "draft",
        "status.published": "published",
        "status.archived": "archived",
        "role.member": "member",
        "role.coordinator": "coordinator",
        "role.owner": "owner",
        "mail.resetSubject": "Reset your {app} password",
        "mail.resetTitle": "Choose a new password",
        "mail.greeting": "Hello {name},",
        "mail.resetIntro": (
            "Someone asked to reset the password on this account. If that was you, "
            "use the link below — it works once and expires in {hours}."
        ),
        "mail.resetAction": "Choose a new password",
        "mail.resetIgnore": (
            "If you did not ask for this, ignore this email. "
            "Your password has not changed."
        ),
        "mail.inviteSubject": "{inviter} invited you to {department}",
        "mail.inviteTitle": "You have been invited to {department}",
        "mail.inviteIntro": (
            "{inviter} has invited you to join {department} on {app} as {role}. "
            "Accepting takes a moment and needs an account with this email address."
        ),
        "mail.inviteAction": "Accept the invitation",
        "mail.inviteExpiry": "This invitation expires on {date}.",
        "mail.linkFallback": "If the link does not open, paste this into your browser:",
        "mail.hoursOne": "1 hour",
        "mail.hoursTwo": "2 hours",
        "mail.hoursFew": "{n} hours",
        "mail.hoursMany": "{n} hours",
    },
    "fr": {
        "pdf.night": "Nuit",
        "pdf.date": "Date",
        "pdf.day": "Jour",
        "pdf.points": "Pts",
        "pdf.onCall": "De garde",
        "pdf.nobody": "— personne de garde —",
        "pdf.holidayShort": "fér",
        "pdf.on": "Nb",
        "pdf.shifts": "Gardes",
        "pdf.pointsFull": "Points",
        "pdf.workload": "Charge de travail",
        "pdf.doctor": "Médecin",
        "pdf.grade": "Grade",
        "pdf.weekend": "Week-end",
        "pdf.holiday": "Férié",
        "pdf.none": "aucun",
        "pdf.meta": "{nights} nuits · {shifts} gardes",
        "pdf.balance": "équilibre {value} %",
        "pdf.generated": "généré le {date}",
        "pdf.period": "du {start} au {end}",
        "pdf.legendWeekend": "Week-end",
        "pdf.legendHoliday": "Jour férié",
        "pdf.legendWeights": "Poids : jour ouvré 1,0 · samedi 1,5 · dimanche et fériés 2,0",
        "pdf.page": "Page {page} sur {pages}",
        "pdf.shortTitle": "{count} nuits incomplètement couvertes",
        "pdf.shortOne": "1 nuit incomplètement couverte",
        "status.draft": "brouillon",
        "status.published": "publié",
        "status.archived": "archivé",
        "role.member": "membre",
        "role.coordinator": "coordinateur",
        "role.owner": "responsable",
        "mail.resetSubject": "Réinitialiser votre mot de passe {app}",
        "mail.resetTitle": "Choisissez un nouveau mot de passe",
        "mail.greeting": "Bonjour {name},",
        "mail.resetIntro": (
            "Une réinitialisation du mot de passe de ce compte a été demandée. "
            "Si c'était vous, utilisez le lien ci-dessous : il ne fonctionne "
            "qu'une fois et expire dans {hours}."
        ),
        "mail.resetAction": "Choisir un nouveau mot de passe",
        "mail.resetIgnore": (
            "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message. "
            "Votre mot de passe n'a pas changé."
        ),
        "mail.inviteSubject": "{inviter} vous invite à rejoindre {department}",
        "mail.inviteTitle": "Vous êtes invité à rejoindre {department}",
        "mail.inviteIntro": (
            "{inviter} vous invite à rejoindre {department} sur {app} en tant que {role}. "
            "L'acceptation prend un instant et nécessite un compte avec cette adresse."
        ),
        "mail.inviteAction": "Accepter l'invitation",
        "mail.inviteExpiry": "Cette invitation expire le {date}.",
        "mail.linkFallback": "Si le lien ne s'ouvre pas, copiez ceci dans votre navigateur :",
        "mail.hoursOne": "1 heure",
        "mail.hoursTwo": "2 heures",
        "mail.hoursFew": "{n} heures",
        "mail.hoursMany": "{n} heures",
    },
    "ar": {
        "pdf.night": "الليلة",
        "pdf.date": "التاريخ",
        "pdf.day": "اليوم",
        "pdf.points": "نقاط",
        "pdf.onCall": "المناوبون",
        "pdf.nobody": "— لا أحد مناوب —",
        "pdf.holidayShort": "عيد",
        "pdf.on": "العدد",
        "pdf.shifts": "المناوبات",
        "pdf.pointsFull": "النقاط",
        "pdf.workload": "عبء العمل",
        "pdf.doctor": "الطبيب",
        "pdf.grade": "الدرجة",
        "pdf.weekend": "عطلة الأسبوع",
        "pdf.holiday": "عيد",
        "pdf.none": "لا أحد",
        "pdf.meta": "{nights} ليلة · {shifts} مناوبة",
        "pdf.balance": "التوازن {value}%",
        "pdf.generated": "أُنشئ في {date}",
        "pdf.period": "من {start} إلى {end}",
        "pdf.legendWeekend": "عطلة نهاية الأسبوع",
        "pdf.legendHoliday": "عطلة رسمية",
        "pdf.legendWeights": "الأوزان: يوم عمل 1.0 · السبت 1.5 · الأحد والأعياد 2.0",
        "pdf.page": "صفحة {page} من {pages}",
        "pdf.shortTitle": "{count} ليالٍ غير مغطاة بالكامل",
        "pdf.shortOne": "ليلة واحدة غير مغطاة بالكامل",
        "status.draft": "مسودة",
        "status.published": "منشور",
        "status.archived": "مؤرشف",
        "role.member": "عضو",
        "role.coordinator": "منسّق",
        "role.owner": "مالك",
        "mail.resetSubject": "إعادة تعيين كلمة المرور في {app}",
        "mail.resetTitle": "اختر كلمة مرور جديدة",
        "mail.greeting": "مرحباً {name}،",
        "mail.resetIntro": (
            "طُلبت إعادة تعيين كلمة المرور لهذا الحساب. إن كنت أنت من طلب ذلك، "
            "فاستخدم الرابط أدناه — يعمل مرة واحدة وتنتهي صلاحيته خلال {hours}."
        ),
        "mail.resetAction": "اختيار كلمة مرور جديدة",
        "mail.resetIgnore": "إن لم تطلب ذلك، تجاهل هذه الرسالة. لم تتغيّر كلمة مرورك.",
        "mail.inviteSubject": "دعاك {inviter} للانضمام إلى {department}",
        "mail.inviteTitle": "لقد دُعيت للانضمام إلى {department}",
        "mail.inviteIntro": (
            "دعاك {inviter} للانضمام إلى {department} في {app} بصفة {role}. "
            "القبول لا يستغرق سوى لحظة ويتطلب حساباً بهذا البريد الإلكتروني."
        ),
        "mail.inviteAction": "قبول الدعوة",
        "mail.inviteExpiry": "تنتهي صلاحية هذه الدعوة في {date}.",
        "mail.linkFallback": "إذا لم يفتح الرابط، فانسخ هذا إلى متصفحك:",
        "mail.hoursOne": "ساعة واحدة",
        "mail.hoursTwo": "ساعتان",
        "mail.hoursFew": "{n} ساعات",
        "mail.hoursMany": "{n} ساعة",
    },
}


def normalise(lang: str | None) -> str:
    """Accept 'fr', 'fr-CA', 'ar-TN' or an Accept-Language header."""
    if not lang:
        return "en"
    for part in str(lang).replace(" ", "").split(","):
        code = part.split(";")[0].split("-")[0].lower()
        if code in SUPPORTED:
            return code
    return "en"


class Translator:
    """A tiny bound translator, handed to Jinja as `t`."""

    def __init__(self, lang: str):
        self.lang = normalise(lang)
        self.dir = "rtl" if self.lang in RTL else "ltr"

    def __call__(self, key: str, **vars) -> str:
        text = CATALOG.get(self.lang, {}).get(key) or CATALOG["en"].get(key, key)
        for name, value in vars.items():
            text = text.replace("{" + name + "}", str(value))
        return text

    # ── dates, spelled out rather than left to the host's locales ──

    def month(self, index: int) -> str:
        return MONTHS[self.lang][index - 1]

    def month_year(self, year: int, month: int) -> str:
        return f"{self.month(month)} {year}"

    def weekday(self, day: dt.date, short: bool = False) -> str:
        table = WEEKDAYS_SHORT if short else WEEKDAYS
        return table[self.lang][day.weekday()]

    def long_date(self, day: dt.date) -> str:
        return f"{self.weekday(day)} {day.day} {self.month(day.month)} {day.year}"

    def short_date(self, day: dt.date) -> str:
        return f"{day.day} {self.month(day.month)[:3]}"

    def number(self, value: float, digits: int = 1) -> str:
        """French writes 1,5 where English writes 1.5."""
        rounded = round(float(value), digits)
        text = f"{rounded:g}"
        return text.replace(".", ",") if self.lang == "fr" else text

    def status(self, status) -> str:
        value = getattr(status, "value", status)
        return self(f"status.{value}")

    def role(self, role) -> str:
        return self(f"role.{getattr(role, 'value', role)}")

    def hours(self, n: int) -> str:
        """Arabic counts in one/two/few/many, so a bare "{n} hours" will not do."""
        n = int(n)
        if n == 1:
            key = "mail.hoursOne"
        elif n == 2:
            key = "mail.hoursTwo"
        elif 3 <= n % 100 <= 10:
            key = "mail.hoursFew"
        else:
            key = "mail.hoursMany"
        return self(key, n=n)

    @property
    def weekday_headers(self) -> list[str]:
        return WEEKDAYS_SHORT[self.lang]
