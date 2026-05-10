# SPDX-FileCopyrightText: 2024 Custom GNU Health
# SPDX-License-Identifier: GPL-3.0-or-later

import csv
import io
import calendar
from datetime import datetime, date
import logging

from trytond.exceptions import UserError
from trytond.model import fields, ModelSQL, ModelView, Unique
from trytond.pool import Pool
from trytond.pyson import Bool, Eval
from trytond.transaction import Transaction
from trytond.wizard import Button, StateTransition, StateView, Wizard

__all__ = [
    'MedicationPurchasePackage',
    'MedicationAudit',
    'LoadedPrescriptionAudit',
    'CreatePackageStart',
    'CreatePackageWizard',
    'SelectPrescriptionStart',
    'LoadPrescriptionResult',
    'SelectPrescriptionWizard',
    'ExportResult',
    'PrescriptionAuditExport',
]
logger = logging.getLogger(__name__)


class MedicationPurchasePackage(ModelSQL, ModelView):
    'Paquete de Compra de Medicamentos'
    __name__ = 'gnuhealth.medication.purchase.package'

    name = fields.Char('Nombre', readonly=True)
    date = fields.Date('Fecha', readonly=True)
    created_by = fields.Many2One('res.user', 'Creado por', readonly=True)
    notes = fields.Text('Observaciones', readonly=True)
    audit_lines = fields.One2Many(
        'gnuhealth.medication.audit', 'package', 'Líneas de Auditoría',
        readonly=True)

    @classmethod
    def create(cls, vlist):
        pool = Pool()
        Sequence = pool.get('ir.sequence')
        ModelData = pool.get('ir.model.data')
        seq_id = ModelData.get_id(
            'z_001_prescription_audit', 'seq_purchase_package')
        sequence = Sequence(seq_id)
        vlist = [dict(v) for v in vlist]
        for vals in vlist:
            vals['name'] = sequence.get()
            vals['date'] = date.today()
            vals['created_by'] = Transaction().user
        return super().create(vlist)

    @classmethod
    def write(cls, *args):
        raise UserError('Los paquetes de compra no se pueden modificar.')

    @classmethod
    def delete(cls, records):
        raise UserError('Los paquetes de compra no se pueden eliminar.')


class MedicationAudit(ModelSQL, ModelView):
    'Auditoría de Recetas'
    __name__ = 'gnuhealth.medication.audit'

    source_prescription = fields.Many2One(
        'gnuhealth.prescription.order', 'Cargar Receta',
        states={'invisible': Bool(Eval('prescription_line', False))},
        depends=['prescription_line'],
        help='Seleccione una receta para cargar todas sus líneas de medicamentos')

    prescription_line = fields.Many2One(
        'gnuhealth.prescription.line', 'Línea de Receta',
        readonly=True,
        help='La línea de receta (medicamento) que se está auditando')

    prescription = fields.Function(
        fields.Many2One('gnuhealth.prescription.order', 'Receta'),
        'get_from_line')

    prescription_issue_date = fields.Function(
        fields.Date('Fecha Emision Prescripcion'),
        'get_from_line')

    patient = fields.Function(
        fields.Many2One('gnuhealth.patient', 'Paciente'),
        'get_from_line')

    medicament = fields.Function(
        fields.Many2One('gnuhealth.medicament', 'Medicamento'),
        'get_from_line')

    audit_state = fields.Selection([
        ('pending', 'Pendiente'),
        ('aprobada', 'Aprobada'),
        ('rechazada', 'Rechazada'),
    ], 'Estado Auditoría', sort=False,
        states={'readonly': True},
        help='Estado de auditoría para este medicamento')

    audit_notes = fields.Text('Notas',
        states={'readonly': Eval('audit_state') != 'pending'},
        depends=['audit_state'],
        help='Notas sobre la decisión de auditoría para este medicamento')

    audit_date = fields.DateTime('Fecha Auditoría',
        states={'readonly': True},
        help='Fecha en que se auditó este medicamento')
    audit_date_display = fields.Function(
        fields.Char('Fecha y Hora Auditoria'),
        'get_audit_date_display')

    audit_user = fields.Many2One('res.user', 'Auditor',
        states={'readonly': True},
        help='Usuario que auditó este medicamento')

    is_audit_overseer = fields.Function(
        fields.Boolean('Es Supervisor de Auditoría'),
        'get_is_audit_overseer')

    package = fields.Many2One(
        'gnuhealth.medication.purchase.package', 'Paquete',
        readonly=True,
        help='Paquete de compra al que pertenece este registro')

    is_packaged = fields.Function(
        fields.Boolean('En Paquete'),
        'get_is_packaged')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()
        cls._sql_constraints = [
            ('prescription_line_unique',
                Unique(table, table.prescription_line),
                'Cada línea de medicamento solo puede ser auditada una vez.'),
        ]
        cls._buttons.update({
            'approve_line': {
                'invisible': Eval('audit_state') != 'pending',
                'depends': ['audit_state'],
            },
            'reject_line': {
                'invisible': Eval('audit_state') != 'pending',
                'depends': ['audit_state'],
            },
            'reset_line': {},
        })

    @classmethod
    def _current_user_is_audit_overseer(cls):
        return cls._current_user_has_group('z_supervisosr_auditor_recetas')

    @classmethod
    def _current_user_is_auditor(cls):
        return cls._current_user_has_group('z_auditor_recetas')

    @classmethod
    def _current_user_is_reception(cls):
        return cls._current_user_has_group('z_recepcion_recetas')

    @classmethod
    def _current_user_has_group(cls, group_xml_id):
        pool = Pool()
        User = pool.get('res.user')
        ModelData = pool.get('ir.model.data')
        try:
            group_id = ModelData.get_id('z_001_prescription_audit', group_xml_id)
        except KeyError:
            return False
        current_user = User(Transaction().user)
        return any(g.id == group_id for g in current_user.groups)

    @classmethod
    def _ensure_audit_role(cls):
        if not (
                cls._current_user_is_auditor()
                or cls._current_user_is_audit_overseer()):
            raise UserError(
                'No tiene los permisos necesarios para auditar recetas.')

    @classmethod
    def _ensure_auditor_role(cls):
        if not cls._current_user_is_auditor():
            raise UserError(
                'No tiene los permisos necesarios para aceptar o rechazar '
                'recetas.')

    @classmethod
    def _ensure_reception_role(cls):
        if not cls._current_user_is_reception():
            raise UserError(
                'No tiene los permisos necesarios para cargar recetas.')

    @classmethod
    def _ensure_creation_role(cls):
        if (
                cls._current_user_is_auditor()
                or cls._current_user_is_audit_overseer()):
            raise UserError(
                'Los perfiles de auditor y supervisor no pueden crear '
                'registros de auditoria.')
        cls._ensure_reception_role()

    @classmethod
    def get_from_line(cls, records, name):
        result = {}
        for record in records:
            line = record.prescription_line
            if not line:
                result[record.id] = None
                continue
            if name == 'prescription':
                result[record.id] = line.name.id if line.name else None
            elif name == 'prescription_issue_date':
                result[record.id] = (
                    line.name.prescription_date.date()
                    if line.name and line.name.prescription_date else None)
            elif name == 'patient':
                result[record.id] = (
                    line.name.patient.id
                    if line.name and line.name.patient else None)
            elif name == 'medicament':
                result[record.id] = (
                    line.medicament.id if line.medicament else None)
        return result

    @classmethod
    def get_is_audit_overseer(cls, records, name):
        is_overseer = cls._current_user_is_audit_overseer()
        return {r.id: is_overseer for r in records}

    @classmethod
    def get_is_packaged(cls, records, name):
        return {r.id: bool(r.package) for r in records}

    @classmethod
    def get_audit_date_display(cls, records, name):
        result = {}
        for record in records:
            if record.audit_date:
                result[record.id] = record.audit_date.strftime(
                    '%Y-%m-%d %H:%M:%S')
            else:
                result[record.id] = ''
        return result

    @staticmethod
    def default_audit_state():
        return 'pending'

    @classmethod
    def _get_prescription_code(cls, prescription):
        return (
            getattr(prescription, 'prescription_id', None)
            or getattr(prescription, 'rec_name', None)
            or 'ID %s' % prescription.id)

    @classmethod
    def _create_prescription_audit_lines(cls, prescription_lines):
        return super().create([
            {'prescription_line': line.id}
            for line in prescription_lines
        ])

    @classmethod
    def _build_load_message(cls, prescription, loaded_count, skipped_count):
        prescription_code = cls._get_prescription_code(prescription)
        if skipped_count:
            return (
                'La receta "%s" ya tenia %s linea(s) cargadas. '
                'Se agregaron %s linea(s) faltantes.'
                % (prescription_code, skipped_count, loaded_count))
        return (
            'La receta "%s" se cargo correctamente con %s linea(s).'
            % (prescription_code, loaded_count))

    @classmethod
    def _has_loaded_prescription(cls, prescription):
        LoadedPrescriptionAudit = Pool().get(
            'gnuhealth.loaded.prescription.audit')

        loaded = LoadedPrescriptionAudit.search([
            ('source_prescription_id', '=', prescription.id),
        ], limit=1)
        if loaded:
            return True

        existing = cls.search([
            ('prescription_line.name', '=', prescription.id),
        ], limit=1)
        return bool(existing)

    @staticmethod
    def _get_prescription_issue_date(prescription):
        issue_date = getattr(prescription, 'prescription_date', None)
        if not issue_date:
            return None
        if hasattr(issue_date, 'date'):
            return issue_date.date()
        return issue_date

    @staticmethod
    def _add_one_calendar_month(issue_date):
        year = issue_date.year
        month = issue_date.month + 1
        if month > 12:
            month = 1
            year += 1
        day = min(issue_date.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)

    @classmethod
    def _validate_prescription_validity(cls, prescription):
        prescription_code = cls._get_prescription_code(prescription)
        issue_date = cls._get_prescription_issue_date(prescription)
        if not issue_date:
            raise UserError(
                'La receta "%s" no tiene fecha de emision y no puede '
                'cargarse en auditoria.'
                % prescription_code)

        valid_until = cls._add_one_calendar_month(issue_date)
        if date.today() > valid_until:
            raise UserError(
                'La receta "%s" esta vencida para auditoria. '
                'Su vigencia era hasta el %s.'
                % (prescription_code, valid_until.strftime('%d/%m/%Y')))

    @classmethod
    def load_prescription(cls, prescription):
        cls._ensure_reception_role()
        prescription_code = cls._get_prescription_code(prescription)
        if cls._has_loaded_prescription(prescription):
            raise UserError(
                'La receta "%s" ya fue cargada anteriormente en auditoria.'
                % prescription_code)

        cls._validate_prescription_validity(prescription)

        prescription_lines = list(prescription.prescription_line or [])
        if not prescription_lines:
            raise UserError(
                'La receta "%s" no tiene lineas de medicamentos para cargar.'
                % prescription_code)

        created_records = cls._create_prescription_audit_lines(
            prescription_lines)
        Pool().get('gnuhealth.loaded.prescription.audit').sync_prescription(
            prescription)
        return {
            'records': created_records,
            'prescription_code': prescription_code,
            'loaded_count': len(created_records),
            'skipped_count': 0,
            'message': cls._build_load_message(
                prescription, len(created_records), 0),
        }

    @classmethod
    def create(cls, vlist):
        cls._ensure_creation_role()
        Prescription = Pool().get('gnuhealth.prescription.order')
        created_records = []
        for vals in vlist:
            vals = dict(vals)
            source_id = vals.pop('source_prescription', None)
            if source_id:
                prescription = Prescription(source_id)
                result = cls.load_prescription(prescription)
                created_records.extend(result['records'])
            elif vals.get('prescription_line'):
                raise UserError(
                    'Las lineas de auditoria solo se pueden cargar a partir '
                    'de una receta.')
            else:
                raise UserError(
                    'Seleccione una receta en el campo "Cargar Receta".')
        return created_records

    @classmethod
    def write(cls, *args):
        actions = iter(args)
        new_args = []
        for records, values in zip(actions, actions):
            values = dict(values)
            if 'audit_state' in values:
                target_state = values['audit_state']
                if (
                        'audit_date' not in values
                        and any(
                            record.audit_state != target_state
                            for record in records)):
                    values['audit_date'] = datetime.utcnow()
            new_args.extend([records, values])
        return super().write(*new_args)

    @classmethod
    @ModelView.button
    def approve_line(cls, records):
        cls._ensure_auditor_role()
        for record in records:
            if record.audit_state != 'pending':
                raise UserError(
                    'Solo se pueden aprobar lineas en estado pendiente.')
        current_user = Pool().get('res.user')(Transaction().user)
        cls.write(records, {
            'audit_state': 'aprobada',
            'audit_date': datetime.utcnow(),
            'audit_user': current_user.id,
        })
        logger.info(
            'Medication audit record(s) approved by %s', current_user.name)

    @classmethod
    @ModelView.button
    def reject_line(cls, records):
        cls._ensure_auditor_role()
        for record in records:
            if record.audit_state != 'pending':
                raise UserError(
                    'Solo se pueden rechazar lineas en estado pendiente.')
        current_user = Pool().get('res.user')(Transaction().user)
        cls.write(records, {
            'audit_state': 'rechazada',
            'audit_date': datetime.utcnow(),
            'audit_user': current_user.id,
        })
        logger.info(
            'Medication audit record(s) rejected by %s', current_user.name)

    @classmethod
    @ModelView.button
    def reset_line(cls, records):
        if not cls._current_user_is_audit_overseer():
            raise UserError(
                'No tiene los permisos necesarios para restablecer la '
                'auditoría.')
        for record in records:
            if record.package:
                raise UserError(
                    'No se pueden restablecer lineas que ya estan asociadas '
                    'a un paquete.')
        cls.write(records, {
            'audit_state': 'pending',
            'audit_user': None,
        })
        logger.info('Medication audit record(s) reset to pending')


class LoadedPrescriptionAudit(ModelSQL, ModelView):
    'Recetas registradas para auditoria'
    __name__ = 'gnuhealth.loaded.prescription.audit'

    source_prescription_id = fields.Integer('ID Receta Fuente', readonly=True)
    prescription_code = fields.Char('Codigo de Receta', readonly=True)
    prescription_issue_date = fields.Date('Fecha Emision', readonly=True)
    audit_load_date = fields.DateTime(
        'Fecha Carga a Auditoria', readonly=True)
    patient = fields.Char('Paciente', readonly=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        table = cls.__table__()
        cls._sql_constraints = [
            ('source_prescription_unique',
                Unique(table, table.source_prescription_id),
                'Cada receta solo puede aparecer una vez en la bandeja.'),
        ]

    @classmethod
    def _ensure_sync_context(cls):
        if not Transaction().context.get('sync_loaded_prescription_audit'):
            raise UserError(
                'La bandeja de recetas cargadas se actualiza solo desde el '
                'flujo de carga de auditoria.')

    @classmethod
    def create(cls, vlist):
        cls._ensure_sync_context()
        return super().create(vlist)

    @classmethod
    def write(cls, *args):
        cls._ensure_sync_context()
        return super().write(*args)

    @classmethod
    def delete(cls, records):
        cls._ensure_sync_context()
        return super().delete(records)

    @classmethod
    def _build_summary_values(cls, prescription, audit_lines):
        prescription_date = None
        if prescription and getattr(prescription, 'prescription_date', None):
            prescription_date = prescription.prescription_date.date()
        patient_name = ''
        if prescription and getattr(prescription, 'patient', None):
            patient_name = prescription.patient.rec_name or ''
        load_dates = [
            line.create_date for line in audit_lines
            if getattr(line, 'create_date', None)
        ]
        return {
            'source_prescription_id': prescription.id,
            'prescription_code': MedicationAudit._get_prescription_code(
                prescription),
            'prescription_issue_date': prescription_date,
            'audit_load_date': min(load_dates) if load_dates else None,
            'patient': patient_name,
        }

    @classmethod
    def sync_prescription(cls, prescription):
        MedicationAudit = Pool().get('gnuhealth.medication.audit')
        audit_lines = MedicationAudit.search([
            ('prescription_line.name', '=', prescription.id)])
        if not audit_lines:
            return

        values = cls._build_summary_values(prescription, audit_lines)
        with Transaction().set_context(
                sync_loaded_prescription_audit=True,
                skip_loaded_prescription_sync=True):
            existing = super(LoadedPrescriptionAudit, cls).search([
                ('source_prescription_id', '=', prescription.id)])
            if existing:
                super(LoadedPrescriptionAudit, cls).write(existing, values)
            else:
                super(LoadedPrescriptionAudit, cls).create([values])

    @classmethod
    def sync_all(cls):
        if Transaction().context.get('skip_loaded_prescription_sync'):
            return

        MedicationAudit = Pool().get('gnuhealth.medication.audit')
        grouped = {}
        for line in MedicationAudit.search([
                ('prescription_line.name', '!=', None)]):
            prescription = line.prescription
            if not prescription:
                continue
            grouped.setdefault(prescription.id, {
                'prescription': prescription,
                'lines': [],
            })['lines'].append(line)

        if not grouped:
            return

        with Transaction().set_context(
                sync_loaded_prescription_audit=True,
                skip_loaded_prescription_sync=True):
            existing_records = super(LoadedPrescriptionAudit, cls).search([])
            existing_by_source = {
                record.source_prescription_id: record
                for record in existing_records
            }
            for source_id, data in grouped.items():
                values = cls._build_summary_values(
                    data['prescription'], data['lines'])
                record = existing_by_source.get(source_id)
                if record:
                    super(LoadedPrescriptionAudit, cls).write([record], values)
                else:
                    super(LoadedPrescriptionAudit, cls).create([values])

    @classmethod
    def search(cls, domain, offset=0, limit=None, order=None, count=False,
            query=False):
        # Tryton may execute search RPCs in a read-only transaction, so this
        # method must not trigger create/write side effects.
        with Transaction().set_context(skip_loaded_prescription_sync=True):
            return super().search(
                domain, offset=offset, limit=limit, order=order,
                count=count, query=query)


class CreatePackageStart(ModelView):
    'Generar solicitud de compra'
    __name__ = 'gnuhealth.medication.purchase.package.create.start'

    valid_count = fields.Integer('Registros válidos', readonly=True)
    skipped_count = fields.Integer('Registros omitidos', readonly=True)
    notes = fields.Text('Observaciones')
    help_text = fields.Text('Que hara este asistente', readonly=True)
    selection_source = fields.Selection([
        ('manual', 'Usar seleccion actual'),
        ('audit_date_range', 'Buscar por rango de fecha de auditoria'),
    ], 'Como seleccionar lineas',
        required=True,
        help='Defina si desea usar la seleccion actual o buscar lineas '
        'aprobadas por fecha de auditoria.')
    audit_date_from = fields.Date(
        'Fecha de auditoria desde',
        states={
            'invisible': Eval('selection_source') != 'audit_date_range',
            'required': Eval('selection_source') == 'audit_date_range',
        },
        depends=['selection_source'])
    audit_date_to = fields.Date(
        'Fecha de auditoria hasta',
        states={
            'invisible': Eval('selection_source') != 'audit_date_range',
            'required': Eval('selection_source') == 'audit_date_range',
        },
        depends=['selection_source'])
    eligible_count = fields.Integer('Lineas a incluir', readonly=True)
    excluded_count = fields.Integer('Lineas excluidas', readonly=True)
    selection_summary = fields.Text('Resumen de seleccion', readonly=True)
    exclusion_summary = fields.Text('Motivos de exclusion', readonly=True)

    @classmethod
    def default_valid_count(cls):
        MedicationAudit = Pool().get('gnuhealth.medication.audit')
        active_ids = Transaction().context.get('active_ids') or []
        records = MedicationAudit.browse(active_ids)
        return sum(
            1 for r in records
            if r.audit_state == 'aprobada' and not r.package)

    @classmethod
    def default_skipped_count(cls):
        MedicationAudit = Pool().get('gnuhealth.medication.audit')
        active_ids = Transaction().context.get('active_ids') or []
        records = MedicationAudit.browse(active_ids)
        return sum(
            1 for r in records
            if r.audit_state != 'aprobada' or r.package)

    @staticmethod
    def default_help_text():
        return (
            'Este asistente genera un paquete de compra con lineas '
            'aprobadas de auditoria que todavia no fueron incluidas en '
            'otro paquete.')

    @classmethod
    def _get_manual_records(cls):
        MedicationAudit = Pool().get('gnuhealth.medication.audit')
        active_ids = Transaction().context.get('active_ids') or []
        if not active_ids:
            return []
        return list(MedicationAudit.browse(active_ids))

    @classmethod
    def _get_initial_range_dates(cls):
        records = cls._get_manual_records()
        dated = [
            record.audit_date.date()
            for record in records
            if getattr(record, 'audit_date', None)
        ]
        if dated:
            return min(dated), max(dated)
        today = date.today()
        return today, today

    @classmethod
    def _get_range_records(cls, date_from, date_to):
        MedicationAudit = Pool().get('gnuhealth.medication.audit')
        if not date_from or not date_to or date_from > date_to:
            return []
        return list(MedicationAudit.search([]))

    @classmethod
    def _summarize_records(cls, records, selection_source, date_from=None,
            date_to=None):
        reasons = {
            'not_approved': 0,
            'already_packaged': 0,
            'missing_audit_date': 0,
            'out_of_range': 0,
        }
        eligible = []

        for record in records:
            if record.audit_state != 'aprobada':
                reasons['not_approved'] += 1
                continue
            if record.package:
                reasons['already_packaged'] += 1
                continue
            if selection_source == 'audit_date_range':
                if not record.audit_date:
                    reasons['missing_audit_date'] += 1
                    continue
                audit_day = record.audit_date.date()
                if audit_day < date_from or audit_day > date_to:
                    reasons['out_of_range'] += 1
                    continue
            eligible.append(record)

        if selection_source == 'manual':
            if records:
                selection_summary = (
                    'Se evaluaran %s linea(s) de la seleccion actual. '
                    'Solo se incluiran las aprobadas y sin paquete.'
                    % len(records))
            else:
                selection_summary = (
                    'No hay lineas seleccionadas. Puede volver con una '
                    'seleccion previa o cambiar a rango por fecha.')
        elif date_from and date_to:
            selection_summary = (
                'Se evaluaran las lineas con fecha de auditoria entre %s y '
                '%s. Solo se incluiran las aprobadas y sin paquete.'
                % (
                    date_from.strftime('%d/%m/%Y'),
                    date_to.strftime('%d/%m/%Y'),
                ))
        else:
            selection_summary = (
                'Indique un rango de fechas de auditoria para buscar lineas '
                'aprobadas sin paquete.')

        exclusion_parts = []
        if reasons['not_approved']:
            exclusion_parts.append(
                '%s sin aprobar' % reasons['not_approved'])
        if reasons['already_packaged']:
            exclusion_parts.append(
                '%s ya incluidas en otro paquete'
                % reasons['already_packaged'])
        if reasons['missing_audit_date']:
            exclusion_parts.append(
                '%s sin fecha de auditoria'
                % reasons['missing_audit_date'])
        if reasons['out_of_range']:
            exclusion_parts.append(
                '%s fuera del rango' % reasons['out_of_range'])

        if exclusion_parts:
            exclusion_summary = 'Se excluyen: %s.' % ', '.join(exclusion_parts)
        else:
            exclusion_summary = (
                'No hay exclusiones con el criterio seleccionado.')

        return {
            'eligible': eligible,
            'eligible_count': len(eligible),
            'excluded_count': len(records) - len(eligible),
            'selection_summary': selection_summary,
            'exclusion_summary': exclusion_summary,
        }

    @classmethod
    def _build_preview(cls, selection_source, date_from=None, date_to=None):
        if selection_source == 'manual':
            records = cls._get_manual_records()
        else:
            records = cls._get_range_records(date_from, date_to)
        return cls._summarize_records(
            records, selection_source, date_from=date_from, date_to=date_to)

    @classmethod
    def default_selection_source(cls):
        if Transaction().context.get('active_ids'):
            return 'manual'
        return 'audit_date_range'

    @classmethod
    def default_audit_date_from(cls):
        return cls._get_initial_range_dates()[0]

    @classmethod
    def default_audit_date_to(cls):
        return cls._get_initial_range_dates()[1]

    @classmethod
    def default_eligible_count(cls):
        preview = cls._build_preview(
            cls.default_selection_source(),
            cls.default_audit_date_from(),
            cls.default_audit_date_to())
        return preview['eligible_count']

    @classmethod
    def default_excluded_count(cls):
        preview = cls._build_preview(
            cls.default_selection_source(),
            cls.default_audit_date_from(),
            cls.default_audit_date_to())
        return preview['excluded_count']

    @classmethod
    def default_selection_summary(cls):
        preview = cls._build_preview(
            cls.default_selection_source(),
            cls.default_audit_date_from(),
            cls.default_audit_date_to())
        return preview['selection_summary']

    @classmethod
    def default_exclusion_summary(cls):
        preview = cls._build_preview(
            cls.default_selection_source(),
            cls.default_audit_date_from(),
            cls.default_audit_date_to())
        return preview['exclusion_summary']

    @fields.depends(
        'selection_source', 'audit_date_from', 'audit_date_to',
        'eligible_count', 'excluded_count',
        'selection_summary', 'exclusion_summary')
    def on_change_selection_source(self):
        self._update_preview()

    @fields.depends(
        'selection_source', 'audit_date_from', 'audit_date_to',
        'eligible_count', 'excluded_count',
        'selection_summary', 'exclusion_summary')
    def on_change_audit_date_from(self):
        self._update_preview()

    @fields.depends(
        'selection_source', 'audit_date_from', 'audit_date_to',
        'eligible_count', 'excluded_count',
        'selection_summary', 'exclusion_summary')
    def on_change_audit_date_to(self):
        self._update_preview()

    def _update_preview(self):
        if self.selection_source == 'audit_date_range':
            if not self.audit_date_from:
                self.audit_date_from = self.__class__.default_audit_date_from()
            if not self.audit_date_to:
                self.audit_date_to = self.__class__.default_audit_date_to()
        preview = self.__class__._build_preview(
            self.selection_source or self.__class__.default_selection_source(),
            self.audit_date_from,
            self.audit_date_to)
        self.eligible_count = preview['eligible_count']
        self.excluded_count = preview['excluded_count']
        self.selection_summary = preview['selection_summary']
        self.exclusion_summary = preview['exclusion_summary']


class CreatePackageWizard(Wizard):
    'Generar solicitud de compra'
    __name__ = 'gnuhealth.medication.purchase.package.create'

    start_state = 'start'
    start = StateView(
        'gnuhealth.medication.purchase.package.create.start',
        'z_001_prescription_audit.view_create_package_start',
        [
            Button('Cancelar', 'end', 'tryton-cancel'),
            Button('Confirmar', 'create_package', 'tryton-ok', default=True),
        ])
    create_package = StateTransition()

    @classmethod
    def _get_target_summary(cls, start):
        StartModel = Pool().get(
            'gnuhealth.medication.purchase.package.create.start')
        if start.selection_source == 'manual':
            records = StartModel._get_manual_records()
        else:
            records = StartModel._get_range_records(
                start.audit_date_from, start.audit_date_to)
        return StartModel._summarize_records(
            records,
            start.selection_source,
            date_from=start.audit_date_from,
            date_to=start.audit_date_to)

    def transition_create_package(self):
        pool = Pool()
        MedicationAudit = pool.get('gnuhealth.medication.audit')
        MedicationPurchasePackage = pool.get(
            'gnuhealth.medication.purchase.package')

        MedicationAudit._ensure_auditor_role()
        if self.start.selection_source == 'audit_date_range':
            if not self.start.audit_date_from or not self.start.audit_date_to:
                raise UserError(
                    'Debe indicar ambas fechas para buscar por auditoria.')
            if self.start.audit_date_from > self.start.audit_date_to:
                raise UserError(
                    'La fecha desde no puede ser mayor que la fecha hasta.')

        summary = self.__class__._get_target_summary(self.start)
        valid = summary['eligible']

        if not valid:
            if self.start.selection_source == 'manual':
                raise UserError(
                    'La seleccion actual no tiene lineas aprobadas y sin '
                    'paquete para generar la solicitud de compra.')
            raise UserError(
                'No se encontraron lineas aprobadas y sin paquete dentro '
                'del rango de fecha de auditoria indicado.')
            raise UserError(
                'No hay medicamentos aprobados sin paquete en la selección.')

        package, = MedicationPurchasePackage.create([{
            'notes': self.start.notes,
        }])
        MedicationAudit.write(valid, {'package': package.id})
        try:
            MedicalPurchaseAudit = pool.get(
                'gnuhealth.medical.purchase.audit')
        except KeyError:
            MedicalPurchaseAudit = None
        if MedicalPurchaseAudit is not None:
            MedicalPurchaseAudit.create_from_package(
                MedicationPurchasePackage(package.id))
        return 'end'

    def end(self):
        return 'reload'


class SelectPrescriptionStart(ModelView):
    'Seleccionar Receta'
    __name__ = 'gnuhealth.medication.audit.select.start'

    prescription = fields.Many2One(
        'gnuhealth.prescription.order', 'Receta',
        required=True,
        help='Receta a cargar en auditoría')


class LoadPrescriptionResult(ModelView):
    'Resultado de Carga de Receta'
    __name__ = 'gnuhealth.medication.audit.load.result'

    prescription_code = fields.Char('Codigo de Receta', readonly=True)
    loaded_count = fields.Integer('Lineas Cargadas', readonly=True)
    skipped_count = fields.Integer('Lineas Ya Existentes', readonly=True)
    message = fields.Text('Resultado', readonly=True)


class CreateTestUsersStart(ModelView):
    'Crear usuarios de prueba'
    __name__ = 'gnuhealth.test.users.create.start'

    notes = fields.Text('Observaciones', readonly=True)

    @staticmethod
    def default_notes():
        return (
            'Este asistente crea o actualiza un usuario de prueba por cada '
            'grupo personalizado de auditoria y compras. Si el usuario ya '
            'existe, se conserva y se asegura su asociacion con el grupo.')


class CreateTestUsersResult(ModelView):
    'Resultado de creacion de usuarios de prueba'
    __name__ = 'gnuhealth.test.users.create.result'

    summary = fields.Text('Resultado', readonly=True)


class SelectPrescriptionWizard(Wizard):
    'Cargar Receta'
    __name__ = 'gnuhealth.medication.audit.select'

    start_state = 'start'
    start = StateView(
        'gnuhealth.medication.audit.select.start',
        'z_001_prescription_audit.view_select_prescription_start',
        [
            Button('Cancelar', 'end', 'tryton-cancel'),
            Button('Confirmar', 'create_records', 'tryton-ok', default=True),
        ])
    create_records = StateTransition()
    result = StateView(
        'gnuhealth.medication.audit.load.result',
        'z_001_prescription_audit.view_load_prescription_result',
        [Button('Cerrar', 'end', 'tryton-ok', default=True)])

    def __init__(self, session_id):
        super().__init__(session_id)
        self.load_result_data = {}

    def transition_create_records(self):
        MedicationAudit = Pool().get('gnuhealth.medication.audit')
        MedicationAudit._ensure_reception_role()
        result = MedicationAudit.load_prescription(self.start.prescription)
        self.load_result_data = {
            'prescription_code': result['prescription_code'],
            'loaded_count': result['loaded_count'],
            'skipped_count': result['skipped_count'],
            'message': result['message'],
        }
        return 'result'

    def default_result(self, fields_names):
        return dict(self.load_result_data)

    def end(self):
        return 'reload'


class CreateTestUsersWizard(Wizard):
    'Crear usuarios de prueba'
    __name__ = 'gnuhealth.test.users.create'

    TEST_USER_SPECS = (
        {
            'module': 'z_001_prescription_audit',
            'group_xml_id': 'z_recepcion_recetas',
            'login': 'test_recepcion_recetas',
            'name': 'Usuario Prueba Recepcion Recetas',
            'password': 'test1234',
        },
        {
            'module': 'z_001_prescription_audit',
            'group_xml_id': 'z_auditor_recetas',
            'login': 'test_auditor_recetas',
            'name': 'Usuario Prueba Auditor Recetas',
            'password': 'test1234',
        },
        {
            'module': 'z_001_prescription_audit',
            'group_xml_id': 'z_supervisosr_auditor_recetas',
            'login': 'test_supervisor_recetas',
            'name': 'Usuario Prueba Supervisor Recetas',
            'password': 'test1234',
        },
        {
            'module': 'z_001_medical_purchases_audit',
            'group_xml_id': 'z_gestor_compras_medicamentos',
            'login': 'test_gestor_compras',
            'name': 'Usuario Prueba Gestor Compras',
            'password': 'test1234',
        },
        {
            'module': 'z_001_medical_purchases_audit',
            'group_xml_id': 'z_auditor_medico_compras_medicamentos',
            'login': 'test_auditor_medico_compras',
            'name': 'Usuario Prueba Auditor Medico Compras',
            'password': 'test1234',
        },
    )

    start_state = 'start'
    start = StateView(
        'gnuhealth.test.users.create.start',
        'z_001_prescription_audit.view_create_test_users_start',
        [
            Button('Cancelar', 'end', 'tryton-cancel'),
            Button('Crear', 'create_users', 'tryton-ok', default=True),
        ])
    create_users = StateTransition()
    result = StateView(
        'gnuhealth.test.users.create.result',
        'z_001_prescription_audit.view_create_test_users_result',
        [Button('Cerrar', 'end', 'tryton-ok', default=True)])

    def __init__(self, session_id):
        super().__init__(session_id)
        self.result_data = {}

    @classmethod
    def _get_group_id(cls, module_name, group_xml_id):
        ModelData = Pool().get('ir.model.data')
        try:
            return ModelData.get_id(module_name, group_xml_id)
        except KeyError:
            return None

    @classmethod
    def _ensure_group_membership(cls, user, group_id):
        user_group_ids = {group.id for group in (user.groups or [])}
        if group_id in user_group_ids:
            return False
        Pool().get('res.user').write([user], {
            'groups': [('add', [group_id])],
        })
        return True

    @classmethod
    def _create_or_update_test_user(cls, spec):
        User = Pool().get('res.user')
        group_id = cls._get_group_id(spec['module'], spec['group_xml_id'])
        if not group_id:
            return {
                'login': spec['login'],
                'password': spec['password'],
                'status': 'omitido por modulo no instalado',
            }
        users = User.search([
            ('login', '=', spec['login']),
        ], limit=1)
        if users:
            membership_added = cls._ensure_group_membership(users[0], group_id)
            return {
                'login': spec['login'],
                'password': spec['password'],
                'status': (
                    'existente y actualizado'
                    if membership_added else 'existente'),
            }

        User.create([{
            'name': spec['name'],
            'login': spec['login'],
            'password': spec['password'],
            'active': True,
            'groups': [('add', [group_id])],
        }])
        return {
            'login': spec['login'],
            'password': spec['password'],
            'status': 'creado',
        }

    @classmethod
    def _build_summary(cls, results):
        lines = [
            'Usuarios de prueba procesados:',
            '',
        ]
        for result in results:
            lines.append(
                '- %s / %s (%s)'
                % (result['login'], result['password'], result['status']))
        return '\n'.join(lines)

    def transition_create_users(self):
        results = [
            self._create_or_update_test_user(spec)
            for spec in self.TEST_USER_SPECS
        ]
        self.result_data = {
            'summary': self._build_summary(results),
        }
        return 'result'

    def default_result(self, fields_names):
        return dict(self.result_data)


class ExportResult(ModelView):
    'Resultado de Exportación'
    __name__ = 'gnuhealth.medication.audit.export.result'

    csv_file = fields.Binary('Archivo CSV', filename='filename')
    filename = fields.Char('Nombre de archivo', readonly=True)


class PrescriptionAuditExport(Wizard):
    'Exportar Auditoría CSV'
    __name__ = 'gnuhealth.medication.audit.export'

    start_state = 'result'
    result = StateView(
        'gnuhealth.medication.audit.export.result',
        'z_001_prescription_audit.view_audit_export_result',
        [Button('Cerrar', 'end', 'tryton-ok', default=True)])

    _STATE_LABELS = {
        'pending': 'Pendiente',
        'aprobada': 'Aprobada',
        'rechazada': 'Rechazada',
    }

    def default_result(self, fields_names):
        MedicationAudit = Pool().get('gnuhealth.medication.audit')
        active_ids = Transaction().context.get('active_ids') or []

        if active_ids:
            records = MedicationAudit.browse(active_ids)
        else:
            records = MedicationAudit.search([])

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'ID Receta', 'Paciente', 'Medicamento',
            'Estado Auditoría', 'Fecha Auditoría', 'Auditor', 'Notas',
        ])

        for record in records:
            try:
                prescription_id = (
                    record.prescription.prescription_id
                    if record.prescription else '')
            except Exception:
                prescription_id = ''
            try:
                patient_name = (
                    record.patient.rec_name if record.patient else '')
            except Exception:
                patient_name = ''
            try:
                medicament_name = (
                    record.medicament.rec_name if record.medicament else '')
            except Exception:
                medicament_name = ''
            try:
                audit_date = (
                    record.audit_date.strftime('%Y-%m-%d %H:%M:%S')
                    if record.audit_date else '')
            except Exception:
                audit_date = ''
            try:
                auditor = record.audit_user.name if record.audit_user else ''
            except Exception:
                auditor = ''

            writer.writerow([
                prescription_id,
                patient_name,
                medicament_name,
                self._STATE_LABELS.get(
                    record.audit_state, record.audit_state or ''),
                audit_date,
                auditor,
                record.audit_notes or '',
            ])

        csv_bytes = output.getvalue().encode('utf-8-sig')
        return {
            'csv_file': csv_bytes,
            'filename': 'auditoria_medicamentos.csv',
        }
