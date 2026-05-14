from datetime import datetime
from types import SimpleNamespace

from trytond.pool import Pool
from trytond.report import Report
from trytond.transaction import Transaction


class MedicationPurchasePackageReport(Report):
    __name__ = 'z_001_prescription_audit.medication_purchase_package'

    @classmethod
    def get_context(cls, records, header, data):
        context = super().get_context(records, header, data)
        package = records[0] if records else None
        user = None
        try:
            user = Pool().get('res.user')(Transaction().user)
        except Exception:
            user = None

        context['package'] = package
        context['summary'] = cls._build_summary(package, user)
        context['report_lines'] = cls._build_lines(package)
        return context

    @classmethod
    def _build_summary(cls, package, user):
        if not package:
            return SimpleNamespace(
                name='',
                date_text='',
                created_by='',
                notes='',
                line_count='0',
                patient_count='0',
                external_line_count='0',
                printed_at='',
                user='',
            )

        audit_lines = list(getattr(package, 'audit_lines', []) or [])
        patient_ids = {
            getattr(getattr(line, 'patient', None), 'id', None)
            for line in audit_lines
            if getattr(line, 'patient', None)
        }
        external_line_count = sum(
            1 for line in audit_lines if getattr(line, 'external_request', None)
        )
        return SimpleNamespace(
            name=getattr(package, 'name', '') or '',
            date_text=cls._format_date(getattr(package, 'date', None)),
            created_by=cls._rec_name(getattr(package, 'created_by', None)),
            notes=getattr(package, 'notes', None) or '',
            line_count=str(len(audit_lines)),
            patient_count=str(len(patient_ids)),
            external_line_count=str(external_line_count),
            printed_at=datetime.now().strftime('%d/%m/%Y %H:%M'),
            user=cls._rec_name(user),
        )

    @classmethod
    def _build_lines(cls, package):
        lines = []
        if not package:
            return lines

        for line in list(getattr(package, 'audit_lines', []) or []):
            prescription_line = getattr(line, 'prescription_line', None)
            quantity = getattr(line, 'external_quantity', None)
            if prescription_line and quantity is None:
                quantity = getattr(prescription_line, 'quantity', None)

            lines.append(SimpleNamespace(
                reference=getattr(line, 'reference_display', None) or '',
                patient=cls._rec_name(getattr(line, 'patient', None)),
                medicament=cls._rec_name(getattr(line, 'medicament', None)),
                quantity='' if quantity is None else str(quantity),
                origin=cls._origin_label(line),
                audit_date=(
                    getattr(line, 'audit_date_display', None)
                    or cls._format_datetime(getattr(line, 'audit_date', None))
                ),
                auditor=cls._rec_name(getattr(line, 'audit_user', None)),
                notes=getattr(line, 'audit_notes', None) or '',
            ))
        return lines

    @staticmethod
    def _rec_name(record):
        if not record:
            return ''
        return (
            getattr(record, 'rec_name', None)
            or getattr(record, 'name', None)
            or ''
        )

    @staticmethod
    def _format_date(value):
        if not value:
            return ''
        return value.strftime('%d/%m/%Y')

    @staticmethod
    def _format_datetime(value):
        if not value:
            return ''
        return value.strftime('%d/%m/%Y %H:%M')

    @classmethod
    def _origin_label(cls, line):
        if getattr(line, 'external_request', None):
            reason = getattr(line, 'external_reason_display', None) or ''
            if reason:
                return 'Solicitud externa - %s' % reason
            return 'Solicitud externa'
        if getattr(line, 'prescription', None):
            return 'Receta'
        return ''
