import re
import difflib
import html
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components


# ---------- Конфигурация путей ----------

BASE_DIR = Path(__file__).resolve().parent
KB_DIR = BASE_DIR / "БЗ"
AGENTS_DIR = BASE_DIR / "Сценарные агенты"
MAIN_DIR = BASE_DIR / "Главный промт"
MAIN_FALLBACK_FILE = BASE_DIR / "Основной промт.txt"


# ---------- Работа с файлами ----------

def get_main_prompt_path() -> Path:
    """
    Главный документ:
    1) Если есть папка "Главный промт" — берём первый .txt/.md файл.
    2) Иначе используем "Основной промт.txt" в корне.
    """
    if MAIN_DIR.exists() and MAIN_DIR.is_dir():
        files = sorted(
            [p for p in MAIN_DIR.iterdir() if p.is_file()],
            key=lambda p: p.name.lower(),
        )
        if not files:
            raise FileNotFoundError('В папке "Главный промт" нет файлов')
        preferred = None
        for f in files:
            if f.suffix.lower() in {".txt", ".md"}:
                preferred = f
                break
        return preferred or files[0]

    if MAIN_FALLBACK_FILE.exists():
        return MAIN_FALLBACK_FILE

    raise FileNotFoundError(
        'Не найден ни каталог "Главный промт", ни файл "Основной промт.txt"'
    )


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def normalize_title_for_match(title: str) -> str:
    """
    Приводим строки к удобному виду для поиска:
    - убираем двоеточия
    - сжимаем пробелы
    - приводим к lower
    """
    no_colon = title.replace(":", " ")
    collapsed = re.sub(r"\s+", " ", no_colon)
    return collapsed.strip().lower()


def find_kb_file_by_title(raw_title: str) -> Path | None:
    """
    Ищет файл в папке БЗ по заголовку:
    "Правило 3: ПОДТВЕРЖДЕНИЕ ЗАКАЗА" -> "Правило 3 ПОДТВЕРЖДЕНИЕ ЗАКАЗА"
    Сравнение по началу имени файла (без .txt), без учёта регистра.
    """
    if not KB_DIR.exists():
        return None

    target = normalize_title_for_match(raw_title)

    for file in KB_DIR.iterdir():
        if not file.is_file():
            continue
        base = file.stem
        norm = normalize_title_for_match(base)
        if norm.startswith(target):
            return file

    return None


def find_agent_file_by_name(agent_name: str) -> Path | None:
    """
    Ищет файл сценарного агента по имени, например "cleaner_finance_handler".
    Сначала точное совпадение имени файла без расширения, потом по подстроке.
    """
    if not AGENTS_DIR.exists():
        return None

    candidates = [p for p in AGENTS_DIR.iterdir() if p.is_file()]
    lower_target = agent_name.lower()

    for file in candidates:
        if file.stem.lower() == lower_target:
            return file

    for file in candidates:
        if lower_target in file.stem.lower():
            return file

    return None


# ---------- Парсинг ссылок в тексте ----------

LINK_PATTERN = re.compile(
    r'(Используй статью из БЗ:\s*"([^"]+)"|вызывай агента с именем\s*"([^"]+)")',
    re.IGNORECASE,
)


def parse_prompt_with_links(text: str):
    """
    Разбивает текст на сегменты:
    - {'type': 'text', 'text': ...}
    - {'type': 'kb', 'title': ..., 'full_match': ...}
    - {'type': 'agent', 'name': ..., 'full_match': ...}
    """
    segments = []
    last_idx = 0

    for match in LINK_PATTERN.finditer(text):
        start, end = match.span()

        if start > last_idx:
            segments.append({"type": "text", "text": text[last_idx:start]})

        full_match = match.group(1)
        kb_title = match.group(2)
        agent_name = match.group(3)

        if kb_title:
            segments.append(
                {
                    "type": "kb",
                    "title": kb_title,
                    "full_match": full_match,
                }
            )
        elif agent_name:
            segments.append(
                {
                    "type": "agent",
                    "name": agent_name,
                    "full_match": full_match,
                }
            )

        last_idx = end

    if last_idx < len(text):
        segments.append({"type": "text", "text": text[last_idx:]})

    return segments


# ---------- Diff "Было / Стало" ----------

def make_diff_html(old: str, new: str) -> str:
    """
    HTML-таблица diff (слева "Было", справа "Стало") в стиле git.
    """
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    diff = difflib.HtmlDiff(wrapcolumn=90)
    table = diff.make_table(
        old_lines,
        new_lines,
        fromdesc="Было",
        todesc="Стало",
        context=True,
        numlines=3,
    )
    style = """
    <style>
    table.diff {font-family: monospace; font-size: 13px; border-collapse: collapse; width: 100%;}
    .diff_header {background: #f3f4f6; padding: 4px;}
    .diff_next {background: #e5e7eb;}
    .diff_add {background: #e6ffed;}   /* зелёный — добавлено */
    .diff_chg {background: #fff5b1;}   /* жёлтый — изменено */
    .diff_sub {background: #ffeef0;}   /* красный — удалено */
    td, th {padding: 2px 4px; border: 1px solid #e5e7eb;}
    </style>
    """
    return style + table


# ---------- Session state ----------

def init_state():
    if "main_path" not in st.session_state:
        path = get_main_prompt_path()
        content = read_text_file(path)
        st.session_state.main_path = str(path)
        st.session_state.main_original = content
        st.session_state.main_edited = content

    if "linked_path" not in st.session_state:
        st.session_state.linked_path = None
        st.session_state.linked_original = ""
        st.session_state.linked_edited = ""


init_state()


def open_linked_target(kind: str, value: str):
    """
    Открывает файл БЗ или агента и записывает его в session_state
    так, чтобы он отобразился во второй секции.
    """
    if kind == "kb":
        file_path = find_kb_file_by_title(value)
        if file_path is None:
            st.warning(f'Не найден файл в БЗ для "{value}"')
            return
        label = f"БЗ: {file_path.name}"
    elif kind == "agent":
        file_path = find_agent_file_by_name(value)
        if file_path is None:
            st.warning(f'Не найден файл агента для "{value}"')
            return
        label = f"Агент: {file_path.name}"
    else:
        return

    content = read_text_file(file_path)
    st.session_state.linked_path = str(file_path)
    st.session_state.linked_label = label
    st.session_state.linked_original = content
    st.session_state.linked_edited = content


# ---------- UI ----------

st.set_page_config(page_title="Редактор промтов и БЗ", layout="wide")
st.title("Редактор промтов и базы знаний агента")

# Общий layout: слева главный документ, справа связанный (БЗ / агент)
left_col, right_col = st.columns([3, 2])

# ===== 1. ГЛАВНЫЙ ДОКУМЕНТ (слева) =====

with left_col:
    st.markdown("### Главный документ")

    main_path = Path(st.session_state.main_path)
    main_tabs = st.tabs(["Просмотр", "Редактирование"])

    with main_tabs[0]:
        st.caption(f"Файл: `{main_path.name}` (кликабельные ссылки внутри текста)")
        segments = parse_prompt_with_links(
            st.session_state.main_edited  # показываем последнюю версию текста
        )

        # Рендерим по сегментам: обычный текст и “ссылки”, у которых есть кнопка "Развернуть"
        for idx, seg in enumerate(segments):
            if seg["type"] == "text":
                if seg["text"]:
                    st.markdown(seg["text"].replace("\n", "  \n"))
            elif seg["type"] in ("kb", "agent"):
                col_text, col_btn = st.columns([5, 1])
                with col_text:
                    # визуально подсвечиваем как гиперссылку
                    st.markdown(
                        f'<span style="color:#2563eb; text-decoration:underline;">'
                        f'{html.escape(seg["full_match"])}</span>',
                        unsafe_allow_html=True,
                    )
                with col_btn:
                    btn_label = "Развернуть"
                    if st.button(
                        btn_label,
                        key=f"open_seg_{idx}",
                        help="Показать текст правила / агента справа",
                    ):
                        if seg["type"] == "kb":
                            open_linked_target("kb", seg["title"])
                        else:
                            open_linked_target("agent", seg["name"])

    with main_tabs[1]:
        st.caption(f"Файл: `{main_path.name}` — редактирование напрямую")

        edited = st.text_area(
            "Текст главного документа",
            value=st.session_state.main_edited,
            height=500,
            key="main_editor",
        )
        st.session_state.main_edited = edited

        if edited != st.session_state.main_original:
            st.markdown("**Предпросмотр изменений (diff \"Было / Стало\")**")
            diff_html = make_diff_html(st.session_state.main_original, edited)
            components.html(diff_html, height=400, scrolling=True)

            col_save, col_reset = st.columns(2)
            with col_save:
                if st.button("✅ Подтвердить и сохранить главный документ"):
                    write_text_file(main_path, edited)
                    st.session_state.main_original = edited
                    st.success("Главный документ сохранён.")
            with col_reset:
                if st.button("↩️ Отменить изменения (вернуть как было)"):
                    st.session_state.main_edited = st.session_state.main_original
                    st.experimental_rerun()
        else:
            st.info("Изменений в главном документе нет.")


# ===== 2. СВЯЗАННЫЙ ДОКУМЕНТ (справа) =====

with right_col:
    st.markdown("### Связанный документ по ссылке из текста")

    if st.session_state.linked_path is None:
        st.info(
            "Нажмите на синюю подчёркнутую ссылку слева "
            "(`Используй статью из БЗ: ...` или `вызывай агента с именем ...`), "
            "чтобы открыть соответствующий файл для редактирования."
        )
    else:
        linked_path = Path(st.session_state.linked_path)
        label = st.session_state.get("linked_label", linked_path.name)

        st.caption(f"Файл: `{label}`")

        linked_tabs = st.tabs(["Просмотр", "Редактирование"])

        with linked_tabs[0]:
            st.markdown(
                html.escape(st.session_state.linked_edited).replace("\n", "<br>"),
                unsafe_allow_html=True,
            )

        with linked_tabs[1]:
            linked_edited = st.text_area(
                "Текст связанного документа",
                value=st.session_state.linked_edited,
                height=400,
                key="linked_editor",
            )
            st.session_state.linked_edited = linked_edited

            if linked_edited != st.session_state.linked_original:
                st.markdown("**Предпросмотр изменений (diff \"Было / Стало\")**")
                diff_html2 = make_diff_html(
                    st.session_state.linked_original, linked_edited
                )
                components.html(diff_html2, height=350, scrolling=True)

                col_save2, col_reset2 = st.columns(2)
                with col_save2:
                    if st.button("✅ Подтвердить и сохранить связанный документ"):
                        write_text_file(linked_path, linked_edited)
                        st.session_state.linked_original = linked_edited
                        st.success("Связанный документ сохранён.")
                with col_reset2:
                    if st.button("↩️ Отменить изменения связанного документа"):
                        st.session_state.linked_edited = (
                            st.session_state.linked_original
                        )
                        st.experimental_rerun()
            else:
                st.info("Изменений в связанном документе нет.")

        if st.button("Закрыть связанный документ"):
            st.session_state.linked_path = None
            st.session_state.linked_original = ""
            st.session_state.linked_edited = ""
            try:
                st.rerun()
            except Exception:
                try:
                    st.experimental_rerun()
                except Exception:
                    pass