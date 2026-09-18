"""
Lockscreen Date Changer — на движке Nugget.
Меняет формат даты на локскрине iOS 26 через AppleICUDateTimeSymbols.
Запуск от админа, Find My выключен: python lockscreen_date.py
"""
import sys
import os
import plistlib
import traceback
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6 import QtWidgets, QtGui, QtCore
from PySide6.QtCore import Qt, QSettings, QThread, Signal, QLocale

from pymobiledevice3 import usbmux
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.exceptions import PasswordRequiredError

from src.restore.restore import restore_files, FileToRestore


# Языки iPhone (коды AppleLanguages). Названия дат берём из CLDR через QLocale.
IOS_LANGUAGES = [
    "en", "zh-Hans", "zh-Hant", "zh-HK", "ja", "es", "es-419", "fr", "de", "ru", "pt", "pt-PT",
    "it", "ko", "tr", "nl", "ar", "th", "sv", "da", "vi", "nb", "pl", "fi", "id", "he",
    "el", "ro", "hu", "cs", "ca", "sk", "uk", "hr", "ms", "hi", "kk", "bn", "pa", "gu",
    "kn", "ml", "mr", "or", "ta", "te", "ur", "be", "bg", "sr", "sl", "lt", "lv", "et",
    "fa", "sw", "fil", "af", "sq", "am", "hy", "az", "eu", "bs", "my", "km", "gl", "ka",
    "is", "ga", "lo", "mk", "mn", "ne", "si", "uz", "cy", "yue",
]

# Ручные названия поверх CLDR (дни с воскресенья).
PRESET_OVERRIDES = {
    "ru": dict(
        months=["января", "февраля", "марта", "апреля", "мая", "июня",
                "июля", "августа", "сентября", "октября", "ноября", "декабря"],
        weekdays=["Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]),
    "uk": dict(
        months=["січня", "лютого", "березня", "квітня", "травня", "червня",
                "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"],
        weekdays=["Неділя", "Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота"]),
    "be": dict(
        months=["студзеня", "лютага", "сакавіка", "красавіка", "мая", "чэрвеня",
                "ліпеня", "жніўня", "верасня", "кастрычніка", "лістапада", "снежня"],
        weekdays=["Нядзеля", "Панядзелак", "Аўторак", "Серада", "Чацвер", "Пятніца", "Субота"]),
    "kk": dict(
        months=["қаңтар", "ақпан", "наурыз", "сәуір", "мамыр", "маусым",
                "шілде", "тамыз", "қыркүйек", "қазан", "қараша", "желтоқсан"],
        weekdays=["Жексенбі", "Дүйсенбі", "Сейсенбі", "Сәрсенбі", "Бейсенбі", "Жұма", "Сенбі"]),
}

# Языки, где день недели идёт первым — ставим запятую по умолчанию.
COMMA_LANGS = {"ru", "uk", "be", "kk", "en", "de", "pl", "nl", "sv", "da", "nb", "fi",
               "cs", "sk", "hu", "ro", "hr", "bg", "el", "ca", "sr", "sl", "lt", "lv", "et"}

# Только пользовательский файл. Управляемый не трогаем — там твики Nugget.
USER_PREFS = ("HomeDomain", "Library/Preferences/.GlobalPreferences.plist")

# Индексы символов ICU: месяцы (формат/standalone), дни недели (формат/standalone).
ICU_SHORT_MONTHS = ("2", "11")
ICU_SHORT_WEEKDAYS = ("4", "14")


def qlocale_for(lang_code: str, region: str) -> QLocale:
    base = lang_code.split("-")
    parts = [base[0]]
    if len(base) > 1 and base[1].isalpha() and len(base[1]) == 4:
        parts.append(base[1])
    if region and region.isalpha():
        parts.append(region)
    loc = QLocale("_".join(parts))
    if loc.language() == QLocale.Language.C:
        loc = QLocale(base[0])
    return loc


def lang_base(lang_code: str) -> str:
    return lang_code.split("-")[0]


def capitalize(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def default_names(lang_code: str, region: str):
    """Длинные названия: месяцы после числа, дни с воскресенья."""
    ov = PRESET_OVERRIDES.get(lang_base(lang_code))
    if ov:
        return list(ov["months"]), list(ov["weekdays"])
    loc = qlocale_for(lang_code, region)
    months = [loc.monthName(i, QLocale.FormatType.LongFormat) for i in range(1, 13)]
    weekdays = [capitalize(loc.dayName(d, QLocale.FormatType.LongFormat)) for d in (7, 1, 2, 3, 4, 5, 6)]
    return months, weekdays


def standard_names(lang_code: str, region: str):
    """Короткие названия iOS по умолчанию."""
    loc = qlocale_for(lang_code, region)
    months = [loc.monthName(i, QLocale.FormatType.ShortFormat) for i in range(1, 13)]
    weekdays = [loc.dayName(d, QLocale.FormatType.ShortFormat) for d in (7, 1, 2, 3, 4, 5, 6)]
    return months, weekdays


def language_display(lang_code: str) -> str:
    loc = qlocale_for(lang_code, "")
    native_fix = {"en": "English", "es": "Español", "pt": "Português"}
    native = native_fix.get(lang_base(lang_code)) or capitalize(loc.nativeLanguageName())
    english = QLocale.languageToString(loc.language())
    script = ""
    if "Hans" in lang_code:
        script = " (Simplified)"
    elif "Hant" in lang_code:
        script = " (Traditional)"
    elif lang_code == "zh-HK":
        script = " (Hong Kong)"
    elif lang_code == "es-419":
        script = " (Latin America)"
    elif lang_code == "pt-PT":
        script = " (Portugal)"
    if native and native.lower() != english.lower():
        return f"{native} — {english}{script} ({lang_code})"
    return f"{english}{script} ({lang_code})"


def all_regions() -> list[tuple[str, str]]:
    """(код, название) всех территорий CLDR."""
    seen = {}
    for loc in QLocale.matchingLocales(QLocale.Language.AnyLanguage, QLocale.Script.AnyScript, QLocale.Country.AnyCountry):
        t = loc.territory()
        code = QLocale.territoryToCode(t)
        if len(code) == 2 and code.isalpha() and code not in seen:
            seen[code] = QLocale.territoryToString(t)
    return sorted(seen.items(), key=lambda kv: kv[1])


# Локализация интерфейса (RU / EN)
STRINGS = {
    "ru": {
        "title": "Дата на экране блокировки",
        "header": "На движке Nugget от LeminLimez",
        "no_device": "Устройство не подключено",
        "connected": "Подключено: {name}\niOS {version} · локаль устройства: {locale}",
        "language": "Язык",
        "region": "Регион",
        "hint": "Выберите ту же комбинацию, что стоит на iPhone (Настройки → Основные → Язык и регион).",
        "picked": "Выбрано",
        "on_iphone": "На iPhone",
        "match_ok": "совпадает",
        "match_bad": "НЕ совпадает — после применения iPhone переключится на выбранную пару",
        "match_unknown": "устройство не подключено",
        "col_std": "Стандарт (iOS)",
        "col_new": "Заменить на",
        "month": "Месяц",
        "weekday": "День",
        "comma": "Запятая после дня недели",
        "time_keep": "Время: не трогать",
        "time_24": "Время: принудительно 24-часовое",
        "time_12": "Время: принудительно 12-часовое",
        "preview": "Предпросмотр: ",
        "apply": "Применить",
        "reset_names": "Сбросить названия к стандартным длинным",
        "remove": "Убрать твик с устройства",
        "refresh": "Обновить",
        "lang_btn": "Switch to English",
        "status_working": "Применяю… НЕ ОТКЛЮЧАЙТЕ КАБЕЛЬ",
        "status_restoring": "Восстановление на устройство… {p}",
        "done": "Готово! Устройство перезагрузится.\n\nНе забудьте включить «Найти iPhone» обратно.",
        "done_title": "Успех",
        "error_title": "Ошибка",
        "err_findmy": "Нужно выключить «Найти iPhone» (Настройки → [Имя] → Локатор → Найти iPhone).",
        "err_password": "Разблокируйте устройство и нажмите «Доверять» этому компьютеру.",
        "err_nodevice": "Нет подключённого устройства. Подключите iPhone и нажмите «Обновить».",
        "err_admin": "Не удалось сохранить сопряжение с устройством. Запустите программу от имени администратора.",
        "err_unsupported": "iOS {version} не поддерживается: на iOS 27+ применение твиков стирает устройство. Отмена.",
        "err_empty": "Заполните все 19 названий.",
        "confirm_remove": "Удалить AppleICUDateTimeSymbols с устройства? Дата вернётся к стандартной. Язык и регион ({locale}) будут сохранены.",
        "ready_to_apply": "Файл будет записан для локали {locale}. Продолжить?",
    },
    "en": {
        "title": "Lockscreen Date Changer",
        "header": "Built on LeminLimez's Nugget",
        "no_device": "No device connected",
        "connected": "Connected to {name}\niOS {version} · device locale: {locale}",
        "language": "Language",
        "region": "Region",
        "hint": "Pick the same combination your iPhone uses (Settings → General → Language & Region).",
        "picked": "Picked",
        "on_iphone": "On iPhone",
        "match_ok": "match",
        "match_bad": "MISMATCH — after applying, the iPhone will switch to the picked pair",
        "match_unknown": "no device connected",
        "col_std": "Default (iOS)",
        "col_new": "Replace with",
        "month": "Month",
        "weekday": "Day",
        "comma": "Comma after weekday",
        "time_keep": "Time: leave as is",
        "time_24": "Time: force 24-hour",
        "time_12": "Time: force 12-hour",
        "preview": "Preview: ",
        "reset_names": "Reset names to default long forms",
        "apply": "Apply changes",
        "remove": "Remove tweak from device",
        "refresh": "Refresh",
        "lang_btn": "Переключить на русский",
        "status_working": "Applying… DO NOT UNPLUG",
        "status_restoring": "Restoring to device… {p}",
        "done": "All done! Your device will now restart.\n\nRemember to turn Find My back on!",
        "done_title": "Success",
        "error_title": "Error",
        "err_findmy": "Find My must be disabled (Settings → [Your Name] → Find My → Find My iPhone).",
        "err_password": "Unlock your device and tap “Trust” for this computer.",
        "err_nodevice": "No device connected. Plug in your iPhone and press Refresh.",
        "err_admin": "Could not save the device pairing record. Run the program as administrator.",
        "err_unsupported": "iOS {version} is not supported: on iOS 27+ applying tweaks wipes the device. Aborting.",
        "err_empty": "Fill in all 19 names.",
        "confirm_remove": "Remove AppleICUDateTimeSymbols from the device? Date returns to default. Language and region ({locale}) will be kept.",
        "ready_to_apply": "The file will be written for locale {locale}. Continue?",
    },
}


class DeviceInfo:
    def __init__(self, ld, udid, usb):
        vals = ld.all_values
        self.ld = ld
        self.udid = udid
        self.usb = usb
        self.name = vals.get("DeviceName", "iPhone")
        self.version = vals.get("ProductVersion", "?")
        self.build = vals.get("BuildVersion", "?")
        try:
            self.locale = ld.locale or ""
        except Exception:
            self.locale = ""
        try:
            self.language = ld.language or ""
        except Exception:
            self.language = ""


def first_usb_serial():
    for d in usbmux.list_devices():
        if d.is_usb:
            return d.serial
    return None


def find_device():
    serial = first_usb_serial()
    if serial is None:
        return None
    ld = create_using_usbmux(serial=serial)
    return DeviceInfo(ld, serial, True)


def build_symbols(months: list[str], weekdays: list[str]) -> dict:
    symbols = {}
    for idx in ICU_SHORT_MONTHS:
        symbols[idx] = list(months)
    for idx in ICU_SHORT_WEEKDAYS:
        symbols[idx] = list(weekdays)
    return symbols


def apple_locale(lang_code: str, region: str) -> str:
    return f"{lang_base(lang_code)}_{region}"


def apple_languages(lang_code: str, region: str) -> list[str]:
    if "-" in lang_code and lang_code.split("-")[1] in ("419", "PT", "HK"):
        langs = [lang_code]
    else:
        langs = [f"{lang_code}-{region}"]
    if lang_base(lang_code) != "en":
        langs.append("en-US")
    return langs


def build_files(lang_code: str, region: str, symbols: dict | None, time_mode: str) -> list[FileToRestore]:
    # symbols=None → снять твик. Локаль кладём всегда: файл пишется целиком.
    user_plist = {"AppleLocale": apple_locale(lang_code, region),
                  "AppleLanguages": apple_languages(lang_code, region)}
    if symbols is not None:
        user_plist["AppleICUDateTimeSymbols"] = symbols
    if time_mode == "24":
        user_plist["AppleICUForce24HourTime"] = True
        user_plist["AppleICUForce12HourTime"] = False
    elif time_mode == "12":
        user_plist["AppleICUForce24HourTime"] = False
        user_plist["AppleICUForce12HourTime"] = True

    return [
        FileToRestore(contents=plistlib.dumps(user_plist), restore_path=USER_PREFS[1],
                      domain=USER_PREFS[0], owner=0, group=0),
    ]


class RestoreWorker(QThread):
    progress = Signal(object)
    finished_ok = Signal()
    failed = Signal(str, str)

    def __init__(self, ld, files):
        super().__init__()
        self.ld = ld
        self.files = files

    def run(self):
        try:
            restore_files(files=self.files, reboot=True, lockdown_client=self.ld,
                          progress_callback=self.progress.emit)
            self.finished_ok.emit()
        except Exception as e:
            self.failed.emit(str(e), traceback.format_exc())


class MainWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("Nugget", "lockscreen_date")
        self.ui_lang = self.settings.value("ui_lang", "ru", type=str)
        self.device: DeviceInfo | None = None
        self.worker: RestoreWorker | None = None
        self._loading = False
        self.regions = all_regions()
        self._build_ui()
        self.retranslate()
        self.refresh_device()

    # ---------------- UI ----------------
    def t(self, key, **kw):
        return STRINGS[self.ui_lang][key].format(**kw)

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        self.header_lbl = QtWidgets.QLabel()
        self.header_lbl.setStyleSheet("font-size: 15px;")
        layout.addWidget(self.header_lbl)

        self.device_lbl = QtWidgets.QLabel()
        self.device_lbl.setStyleSheet("font-size: 14px;")
        layout.addWidget(self.device_lbl)

        # Язык + регион
        loc_row = QtWidgets.QHBoxLayout()
        self.lang_lbl = QtWidgets.QLabel()
        self.lang_combo = QtWidgets.QComboBox()
        for code in IOS_LANGUAGES:
            self.lang_combo.addItem(language_display(code), code)
        self.region_lbl = QtWidgets.QLabel()
        self.region_combo = QtWidgets.QComboBox()
        self.region_combo.setEditable(True)
        self.region_combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        for code, name in self.regions:
            self.region_combo.addItem(f"{code} — {name}", code)
        completer = QtWidgets.QCompleter([f"{c} — {n}" for c, n in self.regions], self.region_combo)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.region_combo.setCompleter(completer)
        loc_row.addWidget(self.lang_lbl)
        loc_row.addWidget(self.lang_combo, 3)
        loc_row.addSpacing(12)
        loc_row.addWidget(self.region_lbl)
        loc_row.addWidget(self.region_combo, 2)
        layout.addLayout(loc_row)

        self.hint_lbl = QtWidgets.QLabel()
        self.hint_lbl.setWordWrap(True)
        self.hint_lbl.setStyleSheet("color: #9a9a9a; font-size: 12px;")
        layout.addWidget(self.hint_lbl)

        # Сравнение выбранной пары с той, что на устройстве
        self.match_lbl = QtWidgets.QLabel()
        self.match_lbl.setTextFormat(Qt.RichText)
        self.match_lbl.setStyleSheet("font-size: 13px;")
        layout.addWidget(self.match_lbl)

        # Таблица названий
        self.table = QtWidgets.QTableWidget(19, 2)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.table.setMinimumHeight(300)
        layout.addWidget(self.table, 1)

        # Опции
        opt_row = QtWidgets.QHBoxLayout()
        self.comma_chk = QtWidgets.QCheckBox()
        self.time_combo = QtWidgets.QComboBox()
        self.time_combo.addItems(["", "", ""])
        opt_row.addWidget(self.comma_chk)
        opt_row.addStretch()
        opt_row.addWidget(self.time_combo)
        layout.addLayout(opt_row)

        self.preview_lbl = QtWidgets.QLabel()
        self.preview_lbl.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(self.preview_lbl)

        self.status_lbl = QtWidgets.QLabel()
        self.status_lbl.setStyleSheet("color: #e0a030;")
        layout.addWidget(self.status_lbl)

        # Кнопки
        self.apply_btn = QtWidgets.QPushButton()
        self.reset_names_btn = QtWidgets.QPushButton()
        self.remove_btn = QtWidgets.QPushButton()
        self.refresh_btn = QtWidgets.QPushButton()
        self.lang_btn = QtWidgets.QPushButton()
        for b in (self.apply_btn, self.reset_names_btn, self.remove_btn, self.refresh_btn, self.lang_btn):
            b.setMinimumHeight(36)
            layout.addWidget(b)

        # Сигналы
        self.lang_combo.currentIndexChanged.connect(self.on_locale_changed)
        self.region_combo.currentIndexChanged.connect(self.on_locale_changed)
        self.region_combo.lineEdit().editingFinished.connect(self.on_region_typed)
        self.table.itemChanged.connect(self.on_table_changed)
        self.comma_chk.toggled.connect(self.update_preview)
        self.apply_btn.clicked.connect(self.apply)
        self.reset_names_btn.clicked.connect(self.reset_names)
        self.remove_btn.clicked.connect(self.remove_tweak)
        self.refresh_btn.clicked.connect(self.refresh_device)
        self.lang_btn.clicked.connect(self.toggle_ui_lang)

    def retranslate(self):
        self.setWindowTitle(self.t("title"))
        self.header_lbl.setText(self.t("header"))
        self.lang_lbl.setText(self.t("language"))
        self.region_lbl.setText(self.t("region"))
        self.hint_lbl.setText(self.t("hint"))
        self.table.setHorizontalHeaderLabels([self.t("col_std"), self.t("col_new")])
        self.comma_chk.setText(self.t("comma"))
        self.time_combo.setItemText(0, self.t("time_keep"))
        self.time_combo.setItemText(1, self.t("time_24"))
        self.time_combo.setItemText(2, self.t("time_12"))
        self.apply_btn.setText(self.t("apply"))
        self.reset_names_btn.setText(self.t("reset_names"))
        self.remove_btn.setText(self.t("remove"))
        self.refresh_btn.setText(self.t("refresh"))
        self.lang_btn.setText(self.t("lang_btn"))
        self.update_device_label()
        self.fill_std_column()
        self.update_preview()

    def toggle_ui_lang(self):
        self.ui_lang = "en" if self.ui_lang == "ru" else "ru"
        self.settings.setValue("ui_lang", self.ui_lang)
        self.retranslate()

    # ---------------- Данные ----------------
    def current_lang(self) -> str:
        return self.lang_combo.currentData() or "en"

    def current_region(self) -> str:
        data = self.region_combo.currentData()
        if data:
            return data
        text = self.region_combo.currentText().strip().split(" ")[0].upper()
        return text if text else "US"

    def current_locale(self) -> str:
        return f"{self.current_lang()}-{self.current_region()}"

    def settings_key(self) -> str:
        return f"names/{self.current_locale()}"

    def fill_std_column(self):
        std_m, std_w = standard_names(self.current_lang(), self.current_region())
        prev = self._loading
        self._loading = True
        for i in range(12):
            it = QtWidgets.QTableWidgetItem(f"{self.t('month')} {i+1:02d}  ·  {std_m[i]}")
            it.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(i, 0, it)
        for i in range(7):
            it = QtWidgets.QTableWidgetItem(f"{self.t('weekday')} {i+1}  ·  {std_w[i]}")
            it.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(12 + i, 0, it)
        self._loading = prev

    def load_names(self, months, weekdays):
        prev = self._loading
        self._loading = True
        for i in range(12):
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(months[i]))
        for i in range(7):
            self.table.setItem(12 + i, 1, QtWidgets.QTableWidgetItem(weekdays[i]))
        self._loading = prev
        self.update_preview()

    def read_names(self):
        months = [(self.table.item(i, 1).text() if self.table.item(i, 1) else "").strip() for i in range(12)]
        weekdays = [(self.table.item(12 + i, 1).text() if self.table.item(12 + i, 1) else "").strip() for i in range(7)]
        return months, weekdays

    def on_locale_changed(self):
        if self._loading:
            return
        self.fill_std_column()
        # сохранённые названия для локали, иначе — стандартные длинные
        saved = self.settings.value(self.settings_key(), None)
        if saved and isinstance(saved, list) and len(saved) == 20:
            self.load_names(saved[:12], saved[12:19])
            self.comma_chk.setChecked(saved[19] in ("true", "True", True))
        else:
            months, weekdays = default_names(self.current_lang(), self.current_region())
            self.load_names(months, weekdays)
            self.comma_chk.setChecked(lang_base(self.current_lang()) in COMMA_LANGS)
        self.settings.setValue("last_locale", self.current_locale())
        self.update_match_label()

    def on_region_typed(self):
        """Пользователь ввёл код региона руками — найти его в списке."""
        text = self.region_combo.currentText().strip().split(" ")[0].upper()
        idx = self.region_combo.findData(text)
        if idx >= 0 and idx != self.region_combo.currentIndex():
            self.region_combo.setCurrentIndex(idx)
        elif idx >= 0:
            self.region_combo.setCurrentIndex(idx)
            self.on_locale_changed()

    def on_table_changed(self):
        if self._loading:
            return
        self.save_names()
        self.update_preview()

    def save_names(self):
        months, weekdays = self.read_names()
        self.settings.setValue(self.settings_key(), months + weekdays + [str(self.comma_chk.isChecked())])

    def reset_names(self):
        self.settings.remove(self.settings_key())
        months, weekdays = default_names(self.current_lang(), self.current_region())
        self.load_names(months, weekdays)
        self.comma_chk.setChecked(lang_base(self.current_lang()) in COMMA_LANGS)

    def final_weekdays(self, weekdays):
        if self.comma_chk.isChecked():
            return [w + "," if w and not w.endswith(",") else w for w in weekdays]
        return weekdays

    def update_preview(self):
        months, weekdays = self.read_names()
        weekdays = self.final_weekdays(weekdays)
        today = QtCore.QDate.currentDate()
        # QDate: пн=1..вс=7; ICU: вс=0
        wd = weekdays[today.dayOfWeek() % 7]
        mo = months[today.month() - 1]
        lang = lang_base(self.current_lang())
        d = today.day()
        if lang == "en":
            sample = f"{wd} {mo} {d}"
        elif lang in ("de", "da", "nb", "fi", "cs", "sk", "hu", "sl", "hr", "sr"):
            sample = f"{wd} {d}. {mo}"
        elif lang in ("tr", "ja", "zh", "yue", "ko"):
            sample = f"{d} {mo} {wd}"
        else:
            sample = f"{wd} {d} {mo}"
        self.preview_lbl.setText(self.t("preview") + sample)
        if not self._loading:
            self.save_names()

    # ---------------- Устройство ----------------
    def refresh_device(self, silent: bool = False):
        self.device = None
        try:
            self.device = find_device()
        except PasswordRequiredError:
            if not silent:
                self.show_error(self.t("err_password"))
        except Exception as e:
            msg = str(e)
            # 183 = нет прав админа
            if "183" in msg and "MuxException" in type(e).__name__:
                if not silent:
                    self.show_error(self.t("err_admin"), traceback.format_exc())
            # связь пропала (ребут/отключение) — молча
            elif silent or any(k in msg or k in type(e).__name__ for k in (
                    "ConnectionFailed", "ConnectionAborted", "ConnectionTerminated", "Number': 3")):
                print(f"refresh: device not reachable ({type(e).__name__}: {e})")
            else:
                self.show_error(f"{type(e).__name__}: {e}", traceback.format_exc())
        self.update_device_label()
        self.select_device_locale()

    def update_device_label(self):
        if self.device is None:
            self.device_lbl.setText(self.t("no_device"))
        else:
            self.device_lbl.setText(self.t("connected", name=self.device.name,
                                           version=self.device.version,
                                           locale=self.device.locale or "?"))
        has_dev = self.device is not None
        self.apply_btn.setEnabled(has_dev)
        self.remove_btn.setEnabled(has_dev)
        self.update_match_label()

    def update_match_label(self):
        picked = apple_locale(self.current_lang(), self.current_region())
        if self.device is None or not self.device.locale:
            on_phone, color, verdict = "—", "#9a9a9a", self.t("match_unknown")
        else:
            on_phone = self.device.locale.replace("-", "_")
            if on_phone.lower() == picked.lower():
                color, verdict = "#4cc25a", self.t("match_ok")
            else:
                color, verdict = "#e05a5a", self.t("match_bad")
        self.match_lbl.setText(
            f"{self.t('picked')}: <b>{picked}</b><br>"
            f"{self.t('on_iphone')}: <b>{on_phone}</b><br>"
            f"<span style='color:{color}'>● {verdict}</span>"
        )

    def select_device_locale(self):
        """Подставить язык/регион с устройства, иначе — последнее сохранённое."""
        lang_code, region = None, None
        if self.device:
            lang_code = self.device.language or None
            parts = (self.device.locale or "").replace("-", "_").split("_")
            if not lang_code and parts[0]:
                lang_code = parts[0]
            if len(parts) > 1 and len(parts[-1]) == 2:
                region = parts[-1].upper()
        if not lang_code:
            last = self.settings.value("last_locale", "en-US", type=str)
            lang_code, _, region = last.rpartition("-")
            lang_code = lang_code or "ru"
        region = region or "US"

        idx = self.lang_combo.findData(lang_code)
        if idx < 0:
            idx = self.lang_combo.findData(lang_base(lang_code))
        ridx = self.region_combo.findData(region)
        self._loading = True
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        if ridx >= 0:
            self.region_combo.setCurrentIndex(ridx)
        else:
            self.region_combo.setEditText(region)
        self._loading = False
        self.on_locale_changed()

    # ---------------- Применение ----------------
    def check_ready(self) -> bool:
        if self.device is None:
            self.show_error(self.t("err_nodevice"))
            return False
        major = int(self.device.version.split(".")[0])
        if major >= 27:
            self.show_error(self.t("err_unsupported", version=self.device.version))
            return False
        return True

    def time_mode(self) -> str:
        return ("keep", "24", "12")[self.time_combo.currentIndex()]

    def apply(self):
        if not self.check_ready():
            return
        months, weekdays = self.read_names()
        if any(not m for m in months) or any(not w for w in weekdays):
            self.show_error(self.t("err_empty"))
            return
        if QtWidgets.QMessageBox.question(self, self.t("title"),
                                          self.t("ready_to_apply", locale=self.current_locale())) != QtWidgets.QMessageBox.Yes:
            return
        symbols = build_symbols(months, self.final_weekdays(weekdays))
        files = build_files(self.current_lang(), self.current_region(), symbols, self.time_mode())
        self.start_restore(files)

    def remove_tweak(self):
        if not self.check_ready():
            return
        if QtWidgets.QMessageBox.question(self, self.t("title"),
                                          self.t("confirm_remove", locale=self.current_locale())) != QtWidgets.QMessageBox.Yes:
            return
        files = build_files(self.current_lang(), self.current_region(), None, "keep")
        self.start_restore(files)

    def start_restore(self, files):
        self.set_busy(True)
        self.status_lbl.setText(self.t("status_working"))
        self.worker = RestoreWorker(self.device.ld, files)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_ok.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()

    def set_busy(self, busy: bool):
        for w in (self.apply_btn, self.remove_btn, self.refresh_btn, self.table,
                  self.lang_combo, self.region_combo, self.comma_chk, self.time_combo):
            w.setEnabled(not busy)

    def on_progress(self, p):
        txt = f"({p:5.1f}%)" if isinstance(p, (int, float)) else ""
        self.status_lbl.setText(self.t("status_restoring", p=txt))

    def on_done(self):
        self.set_busy(False)
        self.status_lbl.setText("")
        # телефон перезагружается — не дёргаем его
        self.device = None
        self.update_device_label()
        QtWidgets.QMessageBox.information(self, self.t("done_title"), self.t("done"))

    def on_failed(self, msg: str, tb: str):
        self.set_busy(False)
        self.status_lbl.setText("")
        # обрыв связи после применения = ребут, это успех
        if "'Number': 3" in msg or "ConnectionFailed" in msg:
            self.device = None
            self.update_device_label()
            QtWidgets.QMessageBox.information(self, self.t("done_title"), self.t("done"))
            return
        if "Find My" in msg:
            self.show_error(self.t("err_findmy"), tb)
        elif "PasswordRequired" in msg:
            self.show_error(self.t("err_password"), tb)
        else:
            self.show_error(msg, tb)
        self.refresh_device(silent=True)

    def show_error(self, txt: str, details: str = None):
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Critical)
        box.setWindowTitle(self.t("error_title"))
        box.setText(txt)
        if details:
            box.setDetailedText(details)
        box.exec()


def apply_dark_palette(app: QtWidgets.QApplication):
    app.setStyle("Fusion")
    p = QtGui.QPalette()
    bg, base, text, hl = QtGui.QColor(30, 30, 30), QtGui.QColor(42, 42, 42), QtGui.QColor(230, 230, 230), QtGui.QColor(70, 130, 220)
    p.setColor(QtGui.QPalette.Window, bg)
    p.setColor(QtGui.QPalette.WindowText, text)
    p.setColor(QtGui.QPalette.Base, base)
    p.setColor(QtGui.QPalette.AlternateBase, bg)
    p.setColor(QtGui.QPalette.Text, text)
    p.setColor(QtGui.QPalette.Button, base)
    p.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(90, 150, 240))
    p.setColor(QtGui.QPalette.Highlight, hl)
    p.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(255, 255, 255))
    p.setColor(QtGui.QPalette.ToolTipBase, base)
    p.setColor(QtGui.QPalette.ToolTipText, text)
    p.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.Text, QtGui.QColor(120, 120, 120))
    p.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.ButtonText, QtGui.QColor(120, 120, 120))
    app.setPalette(p)


def ensure_admin():
    """Без прав админа не сохраняется pairing record (MuxException 183). Перезапуск через UAC."""
    if os.name != "nt" or "--no-admin" in sys.argv:
        return
    import ctypes
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            return
        params = " ".join(f'"{a}"' for a in sys.argv)
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, os.getcwd(), 1)
        if rc > 32:
            sys.exit(0)
    except Exception:
        pass


if __name__ == "__main__":
    ensure_admin()
    app = QtWidgets.QApplication(sys.argv)
    apply_dark_palette(app)
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nugget.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QtGui.QIcon(icon_path))
    w = MainWindow()
    w.resize(620, 780)
    w.show()
    sys.exit(app.exec())
