"""설정 창.

인증키 등록과 학교 선택이 여기서 끝나야 한다. 사용자가 이 창을 다시 열
일이 없게 만드는 것이 목표이므로, 인증키 발급 안내와 즉시 검증을 모두
창 안에 둔다.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import (
    APP_DISPLAY_NAME,
    APP_NAME,
    AUTHOR_NAME,
    AUTHOR_URL,
    ISSUES_URL,
    LICENSE_NAME,
    NEIS_PORTAL_URL,
    REPO_URL,
    VERSION,
)
from . import autostart, secrets_store
from .allergens import ALLERGENS
from .config import Config
from .neis import NeisClient, NeisError, ResultKind
from .neis.models import MEAL_TYPE_LABELS, School
from .resources.theme import PALETTE
from .workers import submit

log = logging.getLogger(__name__)

_OK_COLOR = "#1E7B34"
_ERROR_COLOR = "#C5221F"
_WARN_COLOR = "#B06000"
_MUTED_COLOR = "#6B6B6B"

_COLOR_LABELS = {"yellow": "노랑", "pink": "분홍", "sky": "하늘", "mint": "연두"}

GUIDE_STEPS = (
    "1. open.neis.go.kr 접속 후 회원가입",
    "2. 상단 [인증키 신청] 메뉴 선택",
    "3. 활용 목적을 입력하고 신청 (무료 · 즉시 발급)",
    "4. 마이페이지에서 발급된 인증키 복사",
    "5. 아래 칸에 붙여넣고 [키 확인] 클릭",
)


class SettingsDialog(QDialog):
    saved = Signal()

    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._selected: School | None = (
            School.from_config(config.school) if config.school else None
        )
        # 저장된 키가 아니라 지금 입력창에 있는 키로 검증·검색해야 한다
        self._client = NeisClient(lambda: self.key_edit.text().strip())

        self.setWindowTitle(f"{APP_DISPLAY_NAME} 설정")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        self._tab_index = {
            "key": self.tabs.addTab(self._build_key_tab(), "인증키"),
            "school": self.tabs.addTab(self._build_school_tab(), "학교"),
            "display": self.tabs.addTab(self._build_display_tab(), "표시"),
            "allergy": self.tabs.addTab(self._build_allergy_tab(), "알레르기"),
            "info": self.tabs.addTab(self._build_about_tab(), "정보"),
        }
        layout.addWidget(self.tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_values()

    # ------------------------------------------------------------ 인증키 탭

    def _build_key_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)

        layout.addWidget(QLabel("NEIS 인증키", tab))

        row = QHBoxLayout()
        self.key_edit = QLineEdit(tab)
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("발급받은 인증키를 붙여넣으세요")
        self.key_edit.textChanged.connect(self._on_key_changed)
        row.addWidget(self.key_edit, 1)

        self.verify_button = QPushButton("키 확인", tab)
        self.verify_button.clicked.connect(self._on_verify)
        row.addWidget(self.verify_button)
        layout.addLayout(row)

        self.show_key_check = QCheckBox("키 보기", tab)
        self.show_key_check.toggled.connect(
            lambda on: self.key_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        layout.addWidget(self.show_key_check)

        self.key_status = QLabel("", tab)
        self.key_status.setWordWrap(True)
        layout.addWidget(self.key_status)

        if not secrets_store.is_secure():
            warning = QLabel(
                "⚠️ 이 환경에서는 OS 자격증명 저장소를 쓸 수 없어 "
                "인증키가 설정 폴더에 평문으로 저장됩니다.",
                tab,
            )
            warning.setWordWrap(True)
            warning.setStyleSheet(f"color: {_WARN_COLOR};")
            layout.addWidget(warning)

        guide = QGroupBox("인증키가 없으신가요?", tab)
        guide_layout = QVBoxLayout(guide)
        for step in GUIDE_STEPS:
            label = QLabel(step, guide)
            label.setWordWrap(True)
            guide_layout.addWidget(label)
        open_button = QPushButton("발급 페이지 열기 ↗", guide)
        open_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(NEIS_PORTAL_URL))
        )
        guide_layout.addWidget(open_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(guide)

        layout.addStretch(1)
        return tab

    def _on_key_changed(self) -> None:
        self._set_status(self.key_status, "", "")
        self._update_search_enabled()

    def _on_verify(self) -> None:
        key = self.key_edit.text().strip()
        if not key:
            self._set_status(self.key_status, "인증키를 입력해 주세요.", _ERROR_COLOR)
            return
        self.verify_button.setEnabled(False)
        self.verify_button.setText("확인 중...")
        self._set_status(self.key_status, "확인하는 중입니다...", _WARN_COLOR)
        submit(
            self._client.verify_key,
            on_ok=lambda _: self._on_verify_done(None),
            on_err=self._on_verify_done,
        )

    def _on_verify_done(self, error: Exception | None) -> None:
        self.verify_button.setEnabled(True)
        self.verify_button.setText("키 확인")
        if error is None:
            self._set_status(self.key_status, "✅ 유효한 인증키입니다.", _OK_COLOR)
        else:
            text = (
                error.user_text
                if isinstance(error, NeisError)
                else f"확인하지 못했습니다. ({error})"
            )
            prefix = (
                "❌"
                if isinstance(error, NeisError) and error.kind is ResultKind.BAD_KEY
                else "⚠️"
            )
            self._set_status(self.key_status, f"{prefix} {text}", _ERROR_COLOR)
        self._update_search_enabled()

    # -------------------------------------------------------------- 학교 탭

    def _build_school_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)

        layout.addWidget(QLabel("학교 검색", tab))
        row = QHBoxLayout()
        self.search_edit = QLineEdit(tab)
        self.search_edit.setPlaceholderText("학교 이름의 일부를 입력하세요")
        self.search_edit.returnPressed.connect(self._on_search)
        row.addWidget(self.search_edit, 1)
        self.search_button = QPushButton("검색", tab)
        self.search_button.clicked.connect(self._on_search)
        row.addWidget(self.search_button)
        layout.addLayout(row)

        self.result_list = QListWidget(tab)
        self.result_list.setAlternatingRowColors(True)
        self.result_list.itemSelectionChanged.connect(self._on_result_selected)
        self.result_list.itemDoubleClicked.connect(lambda _: self._on_save())
        layout.addWidget(self.result_list, 1)

        self.search_status = QLabel("", tab)
        self.search_status.setWordWrap(True)
        layout.addWidget(self.search_status)

        rule = QFrame(tab)
        rule.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(rule)

        self.selected_label = QLabel("", tab)
        self.selected_label.setWordWrap(True)
        layout.addWidget(self.selected_label)
        return tab

    def _update_search_enabled(self) -> None:
        has_key = bool(self.key_edit.text().strip())
        self.search_edit.setEnabled(has_key)
        self.search_button.setEnabled(has_key)
        if not has_key:
            self._set_status(
                self.search_status, "먼저 인증키를 등록하세요.", _WARN_COLOR
            )
        elif self.search_status.text() == "먼저 인증키를 등록하세요.":
            self._set_status(self.search_status, "", "")

    def _on_search(self) -> None:
        name = self.search_edit.text().strip()
        if not name:
            return
        self.search_button.setEnabled(False)
        self.result_list.clear()
        self._set_status(self.search_status, "검색 중입니다...", _WARN_COLOR)
        submit(
            self._client.search_schools,
            name,
            on_ok=self._on_search_done,
            on_err=self._on_search_failed,
        )

    def _on_search_done(self, schools: list[School]) -> None:
        self.search_button.setEnabled(True)
        self.result_list.clear()
        if not schools:
            self._set_status(
                self.search_status,
                "검색 결과가 없습니다. 정식 명칭의 일부로 검색해 보세요.",
                _ERROR_COLOR,
            )
            return
        for school in schools:
            item = QListWidgetItem(f"{school.school_name}\n    {school.subtitle}")
            item.setData(Qt.ItemDataRole.UserRole, school)
            self.result_list.addItem(item)
            if (
                self._selected
                and school.school_code == self._selected.school_code
                and school.office_code == self._selected.office_code
            ):
                item.setSelected(True)
        note = f"{len(schools)}개를 찾았습니다."
        if len(schools) >= 100:
            note += " 100개까지만 표시합니다. 검색어를 더 자세히 입력하세요."
        self._set_status(self.search_status, note, _WARN_COLOR)

    def _on_search_failed(self, error: Exception) -> None:
        self.search_button.setEnabled(True)
        text = (
            error.user_text
            if isinstance(error, NeisError)
            else f"검색하지 못했습니다. ({error})"
        )
        self._set_status(self.search_status, f"⚠️ {text}", _ERROR_COLOR)

    def _on_result_selected(self) -> None:
        items = self.result_list.selectedItems()
        if not items:
            return
        school = items[0].data(Qt.ItemDataRole.UserRole)
        if isinstance(school, School):
            self._selected = school
            self._refresh_selected_label()

    def _refresh_selected_label(self) -> None:
        if self._selected is None:
            self.selected_label.setText("선택된 학교가 없습니다.")
            return
        school = self._selected
        self.selected_label.setText(
            f"선택: {school.school_name} "
            f"({school.office_code}/{school.school_code})"
        )

    # -------------------------------------------------------------- 표시 탭

    def _build_display_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)

        meal_group = QGroupBox("표시할 급식", tab)
        meal_layout = QHBoxLayout(meal_group)
        self.meal_checks: dict[str, QCheckBox] = {}
        for key, label in MEAL_TYPE_LABELS.items():
            check = QCheckBox(label, meal_group)
            self.meal_checks[key] = check
            meal_layout.addWidget(check)
        meal_layout.addStretch(1)
        layout.addWidget(meal_group)

        form_group = QGroupBox("내용", tab)
        form = QFormLayout(form_group)
        self.grade_combo = QComboBox(form_group)
        self.grade_combo.addItem("전체", None)
        for grade in range(1, 7):
            self.grade_combo.addItem(f"{grade}학년", grade)
        form.addRow("학년 필터", self.grade_combo)

        self.calorie_check = QCheckBox("칼로리 표시", form_group)
        self.allergy_check = QCheckBox("모든 알레르기 번호 표시", form_group)
        self.expand_check = QCheckBox(
            "재료·원산지를 처음부터 펼쳐 두기", form_group
        )
        self.expand_check.setToolTip(
            "펼치지 않아도 포스트잇을 클릭하면 언제든 열고 닫을 수 있습니다."
        )
        form.addRow(self.calorie_check)
        form.addRow(self.allergy_check)
        form.addRow(self.expand_check)
        layout.addWidget(form_group)

        window_group = QGroupBox("창", tab)
        window_form = QFormLayout(window_group)
        self.color_combo = QComboBox(window_group)
        for key in PALETTE:
            self.color_combo.addItem(_COLOR_LABELS.get(key, key), key)
        window_form.addRow("포스트잇 색", self.color_combo)

        opacity_row = QHBoxLayout()
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal, window_group)
        self.opacity_slider.setRange(50, 100)
        self.opacity_value = QLabel("", window_group)
        self.opacity_slider.valueChanged.connect(
            lambda v: self.opacity_value.setText(f"{v}%")
        )
        opacity_row.addWidget(self.opacity_slider, 1)
        opacity_row.addWidget(self.opacity_value)
        window_form.addRow("불투명도", opacity_row)

        self.on_top_check = QCheckBox("항상 위에 표시", window_group)
        window_form.addRow(self.on_top_check)
        layout.addWidget(window_group)

        start_group = QGroupBox("시작", tab)
        start_form = QFormLayout(start_group)
        self.boot_check = QCheckBox("컴퓨터를 켤 때 자동 실행", start_group)
        self.show_on_start_check = QCheckBox("시작할 때 포스트잇 보이기", start_group)
        start_form.addRow(self.boot_check)
        start_form.addRow(self.show_on_start_check)
        if not autostart.is_supported():
            self.boot_check.setEnabled(False)
            self.boot_check.setToolTip(
                "이 환경에서는 자동 시작을 등록할 수 없습니다."
            )
        layout.addWidget(start_group)

        layout.addStretch(1)
        return tab

    # ---------------------------------------------------------- 알레르기 탭

    def _build_allergy_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)

        intro = QLabel(
            "해당하는 항목을 고르면 그 알레르기가 들어간 음식이 "
            "포스트잇에 <b>빨갛게</b> 표시됩니다.",
            tab,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        group = QGroupBox("내 알레르기", tab)
        grid = QGridLayout(group)
        self.allergy_checks: dict[int, QCheckBox] = {}
        for index, (code, name) in enumerate(sorted(ALLERGENS.items())):
            check = QCheckBox(f"{code}. {name}", group)
            self.allergy_checks[code] = check
            grid.addWidget(check, index // 3, index % 3)
        layout.addWidget(group)

        buttons = QHBoxLayout()
        clear_button = QPushButton("모두 해제", tab)
        clear_button.clicked.connect(
            lambda: [c.setChecked(False) for c in self.allergy_checks.values()]
        )
        buttons.addWidget(clear_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        note = QLabel(
            "⚠️ 요리명 뒤 번호는 학교가 등록한 값이고, 재료·원산지 문구는 "
            "이름으로 찾아 표시합니다. 참고용이므로 최종 확인은 학교 공지를 "
            "따라 주세요.",
            tab,
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {_WARN_COLOR};")
        layout.addWidget(note)

        layout.addStretch(1)
        return tab

    # ---------------------------------------------------------------- 정보 탭

    def _build_about_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)

        heading = QLabel(
            f"<span style='font-size:13pt; font-weight:600'>{APP_DISPLAY_NAME}</span>"
            f" &nbsp;<span style='color:{_MUTED_COLOR}'>{APP_NAME} v{VERSION}</span>",
            tab,
        )
        layout.addWidget(heading)

        intro = QLabel(
            "오늘 우리 학교의 급식과 학사일정을, 책상에 붙여 둔 포스트잇처럼 "
            "보여주는 데스크톱 위젯입니다.",
            tab,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        project = QGroupBox("프로젝트", tab)
        project_form = QFormLayout(project)
        project_form.addRow(
            "저장소",
            self._link(REPO_URL, REPO_URL.split("://", 1)[-1], project),
        )
        project_form.addRow(
            "버그·건의", self._link(ISSUES_URL, "이슈 남기기", project)
        )
        project_form.addRow("라이선스", QLabel(LICENSE_NAME, project))
        layout.addWidget(project)

        maker = QGroupBox("만든 사람", tab)
        maker_form = QFormLayout(maker)
        maker_form.addRow(
            AUTHOR_NAME,
            self._link(AUTHOR_URL, f"@{AUTHOR_URL.rstrip('/').rsplit('/', 1)[-1]}", maker),
        )
        layout.addWidget(maker)

        source = QGroupBox("데이터 출처", tab)
        source_layout = QVBoxLayout(source)
        source_layout.addWidget(
            QLabel("교육부 NEIS 교육정보 개방 포털", source)
        )
        source_layout.addWidget(
            self._link(NEIS_PORTAL_URL, NEIS_PORTAL_URL.split("://", 1)[-1], source)
        )
        caution = QLabel(
            "급식·알레르기 정보는 학교가 등록한 자료입니다. 참고용으로만 쓰고 "
            "최종 확인은 학교 공지를 따라 주세요.",
            source,
        )
        caution.setWordWrap(True)
        caution.setStyleSheet(f"color: {_WARN_COLOR};")
        source_layout.addWidget(caution)
        layout.addWidget(source)

        layout.addStretch(1)
        return tab

    @staticmethod
    def _link(url: str, text: str, parent: QWidget) -> QLabel:
        label = QLabel(f"<a href='{url}'>{text}</a>", parent)
        label.setOpenExternalLinks(True)
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        return label

    def show_tab(self, name: str) -> None:
        """이름으로 탭을 고른다. 모르는 이름이면 지금 탭을 그대로 둔다."""
        index = self._tab_index.get(name)
        if index is not None:
            self.tabs.setCurrentIndex(index)

    # ------------------------------------------------------------ 값 입출력

    def _load_values(self) -> None:
        self.key_edit.setText(secrets_store.get_key())

        display = self._config.display
        for key, check in self.meal_checks.items():
            check.setChecked(key in display.get("meal_types", ["lunch"]))
        index = self.grade_combo.findData(display.get("grade_filter"))
        self.grade_combo.setCurrentIndex(max(0, index))
        self.calorie_check.setChecked(bool(display.get("show_calorie", True)))
        self.allergy_check.setChecked(bool(display.get("show_allergy", False)))
        self.expand_check.setChecked(bool(display.get("expand_details", False)))

        alerts = {
            int(code)
            for code in display.get("allergy_alerts", [])
            if str(code).isdigit()
        }
        for code, check in self.allergy_checks.items():
            check.setChecked(code in alerts)

        color_index = self.color_combo.findData(display.get("color", "yellow"))
        self.color_combo.setCurrentIndex(max(0, color_index))
        self.opacity_slider.setValue(int(float(display.get("opacity", 0.95)) * 100))
        self.opacity_value.setText(f"{self.opacity_slider.value()}%")
        self.on_top_check.setChecked(bool(display.get("always_on_top", True)))
        self.show_on_start_check.setChecked(bool(display.get("show_on_start", True)))

        # 자동 시작은 설정 파일이 아니라 OS에 등록된 실제 상태를 보여준다.
        # 사용자가 작업 관리자에서 껐을 수도 있다.
        self._boot_initial = (
            autostart.is_enabled()
            if autostart.is_supported()
            else bool(display.get("start_on_boot", False))
        )
        self.boot_check.setChecked(self._boot_initial)

        self._refresh_selected_label()
        self._update_search_enabled()
        if self._selected is None:
            self.tabs.setCurrentIndex(0)

    def _on_save(self) -> None:
        meal_types = [k for k, c in self.meal_checks.items() if c.isChecked()]
        if not meal_types:
            meal_types = ["lunch"]

        if self._selected is None:
            answer = QMessageBox.question(
                self,
                "학교가 선택되지 않았습니다",
                "학교를 선택하지 않으면 급식과 일정을 표시할 수 없습니다.\n"
                "그래도 저장할까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.tabs.setCurrentIndex(1)
                return

        secrets_store.set_key(self.key_edit.text().strip())

        display = self._config.display
        display["meal_types"] = meal_types
        display["grade_filter"] = self.grade_combo.currentData()
        display["show_calorie"] = self.calorie_check.isChecked()
        display["show_allergy"] = self.allergy_check.isChecked()
        display["expand_details"] = self.expand_check.isChecked()
        display["allergy_alerts"] = sorted(
            code for code, check in self.allergy_checks.items() if check.isChecked()
        )
        display["color"] = self.color_combo.currentData()
        display["opacity"] = self.opacity_slider.value() / 100
        display["always_on_top"] = self.on_top_check.isChecked()
        display["show_on_start"] = self.show_on_start_check.isChecked()
        display["start_on_boot"] = self._apply_autostart()

        self._config.school = self._selected.to_config() if self._selected else None
        self._config.save()

        self.saved.emit()
        self.accept()

    def _apply_autostart(self) -> bool:
        """자동 시작을 실제로 등록하거나 해제하고, 설정에 남길 값을 돌려준다.

        고르지 않은 채 저장만 반복하는 경우에 레지스트리를 건드리지 않도록
        바뀐 때만 손을 댄다. 실패했으면 설정에도 켜졌다고 적지 않는다.
        """
        wanted = self.boot_check.isChecked()
        if wanted == self._boot_initial:
            return wanted
        if autostart.set_enabled(wanted):
            self._boot_initial = wanted
            return wanted

        QMessageBox.warning(
            self,
            "자동 시작을 바꾸지 못했습니다",
            "자동 시작 등록에 실패했습니다. 다른 설정은 그대로 저장됩니다.",
        )
        self.boot_check.setChecked(self._boot_initial)
        return self._boot_initial

    # ------------------------------------------------------------------ 유틸

    @staticmethod
    def _set_status(label: QLabel, text: str, color: str) -> None:
        label.setText(text)
        label.setStyleSheet(f"color: {color};" if color else "")
        label.setVisible(bool(text))
