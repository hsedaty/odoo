(function () {
    'use strict';

    const ITEM_ROWS = ['classes', 'students'];

    const state = {
        years: [],
        groups: [],
        levelColumns: [],
        feeTypes: [],
        dirty: false,
    };

    const table = document.getElementById('sp-prediction-table');
    const saveBtn = document.getElementById('sp-save');
    const reloadBtn = document.getElementById('sp-reload');
    const addYearBtn = document.getElementById('sp-add-year');
    const statusEl = document.getElementById('sp-status');

    if (!table) {
        return;
    }

    function setStatus(message, type) {
        if (!statusEl) {
            return;
        }
        statusEl.textContent = message || '';
        statusEl.classList.remove('is-success', 'is-error');
        if (type === 'success') {
            statusEl.classList.add('is-success');
        }
        if (type === 'error') {
            statusEl.classList.add('is-error');
        }
    }

    async function rpc(route, params) {
        const response = await fetch(route, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                jsonrpc: '2.0',
                method: 'call',
                params: params || {},
                id: Date.now(),
            }),
            credentials: 'same-origin',
        });
        const payload = await response.json();
        if (payload.error) {
            throw new Error(payload.error.message || 'Request failed');
        }
        return payload.result;
    }

    function parseNumber(value) {
        const normalized = String(value || '').replace(/,/g, '').trim();
        if (!normalized) {
            return 0;
        }
        const numeric = Number(normalized);
        return Number.isFinite(numeric) ? numeric : 0;
    }

    function formatNumber(value) {
        return Number(value || 0).toLocaleString('en-US');
    }

    function getLevelValue(yearData, levelId) {
        if (!yearData.level_values) {
            yearData.level_values = {};
        }
        if (!yearData.level_values[String(levelId)]) {
            yearData.level_values[String(levelId)] = {
                classes: 0,
                students: 0,
                fee_amounts: {},
            };
        }
        return yearData.level_values[String(levelId)];
    }

    function getFeeAmount(levelValues, feeTypeId) {
        const feeAmounts = levelValues.fee_amounts || {};
        return Number(feeAmounts[String(feeTypeId)] || 0);
    }

    function feeAmountTotal(levelValues) {
        return state.feeTypes.reduce((acc, feeType) => acc + getFeeAmount(levelValues, feeType.id), 0);
    }

    function rowTotal(levelValues, key) {
        return state.levelColumns.reduce((acc, level) => {
            const value = levelValues[String(level.id)] || {};
            if (key === 'classes' || key === 'students') {
                return acc + Number(value[key] || 0);
            }
            return acc + getFeeAmount(value, key);
        }, 0);
    }

    function rowAvg(levelValues, key) {
        if (!state.levelColumns.length) {
            return 0;
        }
        return rowTotal(levelValues, key) / state.levelColumns.length;
    }

    function blockGrandTotal(levelValues) {
        return state.levelColumns.reduce((acc, level) => {
            const value = levelValues[String(level.id)] || {};
            const students = Number(value.students || 0);
            const feeTotal = feeAmountTotal(value);
            return acc + (students * feeTotal);
        }, 0);
    }

    function createEditableCell(yearIndex, rowKey, levelId, value, editable) {
        const td = document.createElement('td');
        td.className = editable ? 'sp-editable' : 'sp-readonly-cell';
        td.contentEditable = editable ? 'true' : 'false';
        td.dataset.yearIndex = String(yearIndex);
        td.dataset.rowKey = rowKey;
        td.dataset.levelId = String(levelId);
        td.textContent = value ? formatNumber(value) : '';
        return td;
    }

    function buildRows() {
        const baseRows = [
            { key: 'classes', label: 'class_count', isFee: false, editable: false },
            { key: 'students', label: 'student_count', isFee: false, editable: true },
        ];
        const feeRows = state.feeTypes.map((feeType) => ({
            key: feeType.id,
            label: feeType.name,
            isFee: true,
            editable: true,
        }));
        return baseRows.concat(feeRows);
    }

    function appendYearBlock(tbody, yearData, yearIndex) {
        const rows = buildRows();
        const yearRowSpan = rows.length + 1;

        rows.forEach((rowDef, rowOffset) => {
            const tr = document.createElement('tr');

            if (rowOffset === 0) {
                const yearTd = document.createElement('td');
                yearTd.className = 'sp-year-cell';
                yearTd.rowSpan = yearRowSpan;
                yearTd.textContent = yearData.label;
                tr.appendChild(yearTd);

                const ayTd = document.createElement('td');
                ayTd.className = 'sp-academic-cell';
                ayTd.rowSpan = yearRowSpan;
                ayTd.contentEditable = 'true';
                ayTd.dataset.yearIndex = String(yearIndex);
                ayTd.dataset.rowKey = 'academicYear';
                ayTd.textContent = yearData.academic_year_name;
                tr.appendChild(ayTd);
            }

            const itemTd = document.createElement('td');
            itemTd.className = 'sp-left';
            itemTd.textContent = rowDef.label;
            tr.appendChild(itemTd);

            state.levelColumns.forEach((level) => {
                const levelValue = getLevelValue(yearData, level.id);
                const cellValue = rowDef.isFee ? getFeeAmount(levelValue, rowDef.key) : Number(levelValue[rowDef.key] || 0);
                tr.appendChild(createEditableCell(yearIndex, String(rowDef.key), level.id, cellValue, rowDef.editable));
            });

            const itemTotalTd = document.createElement('td');
            itemTotalTd.className = 'sp-item-total-cell';
            const total = rowTotal(yearData.level_values || {}, rowDef.key);
            const avg = rowAvg(yearData.level_values || {}, rowDef.key);
            if (!rowDef.isFee) {
                itemTotalTd.textContent = formatNumber(total);
            } else {
                itemTotalTd.textContent = formatNumber(avg.toFixed(2));
            }
            tr.appendChild(itemTotalTd);

            if (rowOffset === 0) {
                const grandTd = document.createElement('td');
                grandTd.className = 'sp-grand-cell';
                grandTd.rowSpan = 6;
                grandTd.textContent = formatNumber(blockGrandTotal(yearData.level_values || {}));
                tr.appendChild(grandTd);
            }

            tbody.appendChild(tr);
        });

        const subtotalTr = document.createElement('tr');
        subtotalTr.className = 'sp-subtotal-row';

        const subtotalLabelTd = document.createElement('td');
        subtotalLabelTd.className = 'sp-left';
        subtotalLabelTd.textContent = 'Subtotal';
        subtotalTr.appendChild(subtotalLabelTd);

        state.levelColumns.forEach((level) => {
            const value = getLevelValue(yearData, level.id);
            const subtotalTd = document.createElement('td');
            subtotalTd.textContent = formatNumber(Number(value.students || 0) * feeAmountTotal(value));
            subtotalTr.appendChild(subtotalTd);
        });

        const subtotalHintTd = document.createElement('td');
        subtotalHintTd.className = 'sp-item-total-cell';
        subtotalHintTd.textContent = 'Subtotal Revenue';
        subtotalTr.appendChild(subtotalHintTd);

        tbody.appendChild(subtotalTr);
    }

    function rebuildLevelColumns() {
        state.levelColumns = [];
        (state.groups || []).forEach((group) => {
            (group.levels || []).forEach((level) => {
                state.levelColumns.push({
                    id: level.id,
                    name: level.name,
                    groupId: group.id,
                    groupName: group.name,
                });
            });
        });
    }

    function render() {
        table.innerHTML = '';

        const thead = document.createElement('thead');
        const firstHeader = document.createElement('tr');
        const secondHeader = document.createElement('tr');

        firstHeader.innerHTML = '<th rowspan="2">Year</th><th rowspan="2">Academic Y.</th><th rowspan="2" class="sp-left">Items</th>';
        state.groups.forEach((group) => {
            const levels = group.levels || [];
            if (!levels.length) {
                return;
            }
            const th = document.createElement('th');
            th.textContent = group.name;
            th.colSpan = levels.length;
            firstHeader.appendChild(th);

            levels.forEach((level) => {
                const sth = document.createElement('th');
                sth.innerHTML = `<span class="sp-group-subtitle">${level.name || ''}</span>`;
                secondHeader.appendChild(sth);
            });
        });

        firstHeader.innerHTML += '<th rowspan="2">Item Total OR AVG</th><th rowspan="2">Grand Total (REVENUE)</th>';
        thead.appendChild(firstHeader);
        thead.appendChild(secondHeader);
        table.appendChild(thead);

        const tbody = document.createElement('tbody');
        state.years.forEach((yearData, yearIndex) => appendYearBlock(tbody, yearData, yearIndex));
        table.appendChild(tbody);

        if (saveBtn) {
            saveBtn.disabled = !state.dirty;
        }
    }

    function handleTableInput(event) {
        const cell = event.target;
        if (!(cell instanceof HTMLElement)) {
            return;
        }

        const yearIndex = Number(cell.dataset.yearIndex);
        const rowKey = cell.dataset.rowKey;

        if (Number.isNaN(yearIndex) || !rowKey || !state.years[yearIndex]) {
            return;
        }

        if (rowKey === 'academicYear') {
            state.years[yearIndex].academic_year_name = cell.textContent.trim();
            state.dirty = true;
            setStatus('Unsaved changes', '');
            return;
        }

        const isBaseKey = ITEM_ROWS.includes(rowKey);
        const feeTypeId = Number(rowKey);
        const isFeeKey = Number.isInteger(feeTypeId) && feeTypeId > 0;
        if (!isBaseKey && !isFeeKey) {
            return;
        }

        const levelId = Number(cell.dataset.levelId);
        if (Number.isNaN(levelId)) {
            return;
        }

        const parsed = parseNumber(cell.textContent);
        const levelValue = getLevelValue(state.years[yearIndex], levelId);
        if (isBaseKey) {
            levelValue[rowKey] = parsed;
        } else {
            if (!levelValue.fee_amounts) {
                levelValue.fee_amounts = {};
            }
            levelValue.fee_amounts[String(feeTypeId)] = parsed;
        }
        cell.textContent = parsed ? formatNumber(parsed) : '';
        state.dirty = true;
        setStatus('Unsaved changes', '');

        render();
    }

    function payloadForSave() {
        return state.years.map((yearData) => ({
            year_id: yearData.id,
            academic_year_name: yearData.academic_year_name,
            level_values: yearData.level_values || {},
        }));
    }

    async function loadSheet() {
        setStatus('Loading data...', '');
        try {
            const result = await rpc('/school_planning/enrollment-revenue-prediction/load', {});
            state.years = result.years || [];
            state.groups = result.groups || [];
            state.feeTypes = result.fee_types || [];
            rebuildLevelColumns();
            state.dirty = false;
            render();
            setStatus('Loaded from database', 'success');
        } catch (error) {
            setStatus(`Load failed: ${error.message}`, 'error');
        }
    }

    async function saveSheet() {
        setStatus('Saving...', '');
        try {
            await rpc('/school_planning/enrollment-revenue-prediction/save', {
                years: payloadForSave(),
            });
            state.dirty = false;
            render();
            setStatus('Saved to database', 'success');
            await loadSheet();
        } catch (error) {
            setStatus(`Save failed: ${error.message}`, 'error');
        }
    }

    async function addYear() {
        setStatus('Creating academic year...', '');
        try {
            const result = await rpc('/school_planning/enrollment-revenue-prediction/add-year', {});
            if (!result.ok) {
                throw new Error(result.error || 'Could not create year');
            }
            await loadSheet();
            setStatus('Academic year created', 'success');
        } catch (error) {
            setStatus(`Create failed: ${error.message}`, 'error');
        }
    }

    table.addEventListener('blur', handleTableInput, true);
    if (saveBtn) {
        saveBtn.addEventListener('click', saveSheet);
    }
    if (reloadBtn) {
        reloadBtn.addEventListener('click', loadSheet);
    }
    if (addYearBtn) {
        addYearBtn.addEventListener('click', addYear);
    }

    loadSheet();
})();
