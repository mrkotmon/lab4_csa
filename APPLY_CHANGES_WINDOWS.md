# Как перенести исправления в ваш GitHub-репозиторий (Windows PowerShell)

Архив является полной исправленной рабочей копией **без** каталога `.git`. Он основан на варианте из задания и заменяет устаревшие `.bin/.lst/.log` новыми golden-эталонами в `tests/golden`.

## 1. В вашей локальной копии создайте ветку

```powershell
cd C:\Users\User\Desktop\lab4_csa
git status
git switch -c fix/variant-conformance
```

## 2. Распакуйте архив, например в `Downloads`

```powershell
Expand-Archive "$HOME\Downloads\lab4_csa_fixed.zip" "$HOME\Downloads\lab4_csa_fixed" -Force
```

После распаковки исходники будут в каталоге:

```text
$HOME\Downloads\lab4_csa_fixed\lab4_csa_fixed
```

## 3. Удалите устаревшие сгенерированные файлы и старые SVG/PNG-схемы

Актуальные схемы теперь находятся в корневом `README.md` как Mermaid-диаграммы; golden-машинный код и журналы находятся в `tests/golden`.

```powershell
git rm -r --ignore-unmatch examples/*.bin examples/*.lst examples/*.log docs/*.png docs/*.svg
```

## 4. Скопируйте исправленную копию поверх рабочей директории

```powershell
robocopy "$HOME\Downloads\lab4_csa_fixed\lab4_csa_fixed" . /E /XD .git __pycache__ .pytest_cache .mypy_cache .ruff_cache
```

`robocopy` может вернуть ненулевой служебный код при успешном копировании файлов — это его обычное поведение.

## 5. Запустите проверки до commit

```powershell
python -m pip install -e ".[dev]"
ruff format --check src tests
ruff check src tests
mypy src
pytest -v
```

Ожидаемый результат: `19 passed`; `ruff` и `mypy` без ошибок.

## 6. Посмотрите изменения и отправьте ветку

```powershell
git status
git add -A
git commit -m "Fix lab4 variant compliance: byte memory, trap input, vector golden tests"
git push -u origin fix/variant-conformance
```

После push откройте вкладку **Actions** на GitHub и убедитесь, что workflow `CI` завершился зелёной галочкой. После проверки ветку можно слить в `main` через Pull Request.
