# SPDX-FileCopyrightText: 2024 Custom GNU Health
# SPDX-License-Identifier: GPL-3.0-or-later

from trytond.pool import Pool
from . import z_001_prescription_audit


def register():
    Pool.register(
        z_001_prescription_audit.MedicationPurchasePackage,
        z_001_prescription_audit.MedicationAudit,
        z_001_prescription_audit.CreatePackageStart,
        z_001_prescription_audit.SelectPrescriptionStart,
        z_001_prescription_audit.ExportResult,
        module='z_001_prescription_audit', type_='model')
    Pool.register(
        z_001_prescription_audit.CreatePackageWizard,
        z_001_prescription_audit.SelectPrescriptionWizard,
        z_001_prescription_audit.PrescriptionAuditExport,
        module='z_001_prescription_audit', type_='wizard')
