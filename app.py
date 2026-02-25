import re
import difflib
import html
import urllib.parse
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


def render_prompt_html_with_links(text: str) -> str:
    """
    Рендерит текст в HTML, где фрагменты
    - Используй статью из БЗ: "Правило X: НАЗВАНИЕ"
    - вызывай агента с именем "имя_агента"
    становятся кликабельными ссылками.
    """
    parts: list[str] = []
    last_idx = 0

    for match in LINK_PATTERN.finditer(text):
        start, end = match.span()

        # Обычный текст до ссылки
        before = text[last_idx:start]
        parts.append(html.escape(before).replace("\n", "<br>"))

        full_match = match.group(1)
        kb_title = match.group(2)
        agent_name = match.group(3)

        label = html.escape(full_match)
        if kb_title:
            href = (
                "?link_type=kb&target="
                + urllib.parse.quote(kb_title, safe="")
            )
        else:
            href = (
                "?link_type=agent&target="
                + urllib.parse.quote(agent_name, safe="")
            )

        link_html = (
            f'<a href="{href}" '
            f'style="color:#2563eb; text-decoration:underline;">'
            f"{label}</a>"
        )
        parts.append(link_html)

        last_idx = end

    # Хвост после последней ссылки
    tail = text[last_idx:]
    parts.append(html.escape(tail).replace("\n", "<br>"))

    return "".join(parts)


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


def load_linked_from_params():
    """
    Если в URL есть ?link_type=...&target=..., открываем соответствующий файл
    как "связанный документ".
    """
    params = st.experimental_get_query_params()
    link_type = params.get("link_type", [None])[0]
    target = params.get("target", [None])[0]

    if not link_type or not target:
        return

    decoded = urllib.parse.unquote(target)

    if link_type == "kb":
        file_path = find_kb_file_by_title(decoded)
        if file_path is None:
            st.warning(f'Не найден файл в БЗ для "{decoded}"')
            return
        label = f'БЗ: {file_path.name}'
    elif link_type == "agent":
        file_path = find_agent_file_by_name(decoded)
        if file_path is None:
            st.warning(f'Не найден файл агента для "{decoded}"')
            return
        label = f'Агент: {file_path.name}'
    else:
        return

    # Если открывается другой файл — перезаписываем стейт
    if st.session_state.linked_path != str(file_path):
        content = read_text_file(file_path)
        st.session_state.linked_path = str(file_path)
        st.session_state.linked_label = label
        st.session_state.linked_original = content
        st.session_state.linked_edited = content


# ---------- UI ----------

st.set_page_config(page_title="Редактор промтов и БЗ", layout="wide")
st.title("Редактор промтов и базы знаний агента")

# Обновляем связанный документ по query-параметрам
load_linked_from_params()

# ===== 1. ГЛАВНЫЙ ДОКУМЕНТ =====

st.markdown("### Главный документ")

main_path = Path(st.session_state.main_path)
main_tabs = st.tabs(["Просмотр", "Редактирование"])

with main_tabs[0]:
    st.caption(f"Файл: `{main_path.name}` (кликабельные ссылки внутри текста)")

    view_html = render_prompt_html_with_links(
        st.session_state.main_edited  # показываем последнюю версию текста
    )
    st.markdown(view_html, unsafe_allow_html=True)

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


st.markdown("---")

# ===== 2. СВЯЗАННЫЙ ДОКУМЕНТ (БЗ или АГЕНТ) =====

st.markdown("### Связанный документ по ссылке из текста")

if st.session_state.linked_path is None:
    st.info(
        "Нажмите на синюю подчёркнутую ссылку в тексте выше "
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
        # Чистим query-параметры
        st.experimental_set_query_params()
        st.experimental_rerun()