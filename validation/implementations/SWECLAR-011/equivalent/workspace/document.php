<?php
declare(strict_types=1);

function rgb(string $color): array
{
    return [
        hexdec(substr($color, 1, 2)),
        hexdec(substr($color, 3, 2)),
        hexdec(substr($color, 5, 2)),
    ];
}

/** Draw one stored PNG inside a slot without distorting its aspect ratio. */
function drawStoredImage(TCPDF $pdf, array $asset, float $x, float $y, float $width, float $height): void
{
    $sourceWidth = (int) $asset['width'];
    $sourceHeight = (int) $asset['height'];
    if ($sourceWidth < 1 || $sourceHeight < 1 || !is_string($asset['data'])) {
        throw new RuntimeException('Invalid image data');
    }

    $scale = min($width / $sourceWidth, $height / $sourceHeight);
    $drawWidth = $sourceWidth * $scale;
    $drawHeight = $sourceHeight * $scale;
    $drawX = $x + (($width - $drawWidth) / 2);
    $drawY = $y + (($height - $drawHeight) / 2);

    // TCPDF accepts an @-prefixed binary string and embeds the supplied PNG.
    $pdf->Image('@' . $asset['data'], $drawX, $drawY, $drawWidth, $drawHeight, 'PNG');
}

function drawSlotIfPresent(TCPDF $pdf, ?array $asset, float $x, float $y, float $width, float $height, float $opacity = 1.0): void
{
    if ($asset === null) {
        return;
    }
    $pdf->setAlpha($opacity);
    drawStoredImage($pdf, $asset, $x, $y, $width, $height);
    $pdf->setAlpha(1.0);
}

function drawSampleHeading(TCPDF $pdf): void
{
    $pdf->setRTL(false);
    $pdf->SetTextColor(0, 0, 0);
    $pdf->SetFont('dejavusans', 'B', 14);
    $pdf->SetXY(35, 8);
    $pdf->Cell(140, 10, 'SAMPLE / NOT VALID', 0, 0, 'C');
}

function drawFieldPanel(
    TCPDF $pdf,
    string $field,
    string $value,
    array $style,
    float $y,
    array $labels
): void {
    // An invisible field has no panel, label, value, border, or fill, but its
    // reserved panel remains in place so other fields never move.
    if ($style['visible'] !== true) {
        return;
    }

    if ($style['background'] !== null) {
        $pdf->SetFillColor(...rgb($style['background']));
        $pdf->Rect(10, $y, 190, 29, 'F');
    }
    if ($style['border'] === true) {
        $pdf->SetDrawColor(0, 0, 0);
        $pdf->SetLineWidth(0.25);
        $pdf->Rect(10, $y, 190, 29, 'D');
    }

    $pdf->setRTL(false);
    $pdf->SetTextColor(0, 0, 0);
    $pdf->SetFont('dejavusans', '', 8);
    $pdf->SetXY(10, $y);
    $pdf->Cell(90, 5, $labels[$field][0], 0, 0, 'L');

    // Arabic labels occupy the right half of the five-millimetre label row.
    $pdf->setRTL(true);
    // Use an absolute right edge: SetXY's normal RTL coordinate mode
    // mirrors positive X values around the page.
    $pdf->SetXY(10, $y);
    $pdf->Cell(90, 5, $labels[$field][1], 0, 0, 'R');
    $pdf->setRTL(false);

    $pdf->SetTextColor(...rgb($style['color']));
    $pdf->SetFont('dejavusans', $style['weight'] === 'bold' ? 'B' : '', (int) $style['font_size']);
    $hasArabic = preg_match('/\p{Arabic}/u', $value) === 1;
    $pdf->setRTL($hasArabic);
    $pdf->MultiCell(190, 6, $value, 0, $hasArabic ? 'R' : 'L', false, 1, 10, $y + 5, true, 0, false, true, 0, 'T', false);
    $pdf->setRTL(false);
}

/**
 * Render the two-page public sample format. $assets is keyed by asset id and
 * contains the original PNG BLOB plus its independently stored dimensions.
 */
function renderPDF(array $values, array $template, array $assets, string $kind): string
{
    if (!defined('K_TCPDF_THROW_EXCEPTION_ERROR')) {
        define('K_TCPDF_THROW_EXCEPTION_ERROR', true);
    }
    $tcpdfRoot = getenv('TCPDF_ROOT');
    if (!is_string($tcpdfRoot) || $tcpdfRoot === '') {
        throw new RuntimeException('TCPDF is unavailable');
    }
    require_once $tcpdfRoot . '/tcpdf.php';

    // TCPDF normally appends its own tiny "Powered by TCPDF" link at
    // document close. Disable that library watermark so the sample remains
    // wholly application-owned and contains no unsolicited external URL.
    $pdf = new class('L', 'mm', [210, 148], true, 'UTF-8', false) extends TCPDF {
        public function __construct(...$arguments)
        {
            parent::__construct(...$arguments);
            $this->tcpdflink = false;
        }
    };
    $pdf->setPrintHeader(false);
    $pdf->setPrintFooter(false);
    $pdf->SetMargins(10, 5, 10);
    $pdf->SetAutoPageBreak(false);
    $pdf->setCellPadding(0);
    $pdf->setCellMargins(0, 0, 0, 0);
    $pdf->SetCreator('Clar-SWE synthetic document application');
    $pdf->SetAuthor('');
    $pdf->SetTitle('SAMPLE - NOT VALID');
    $pdf->SetSubject('Bilingual sample document');

    $labels = [
        'document_id' => ['Identifiant', 'المعرّف'],
        'name' => ['Nom', 'الاسم'],
        'group' => ['Groupe', 'المجموعة'],
        'contact' => ['Contact', 'جهة الاتصال'],
        'reviewer' => ['Révision', 'المراجعة'],
        'reference' => ['Référence', 'المرجع'],
    ];
    $frontFields = ['document_id', 'name', 'group'];
    $backFields = ['contact', 'reviewer', 'reference'];

    foreach ([$frontFields, $backFields] as $side => $fields) {
        $pdf->AddPage('L', [210, 148]);

        // Image slots are behind text. The watermark is deliberately only a
        // sample_pass feature and is drawn before all field backgrounds/text.
        if ($kind === 'sample_pass' && isset($template['placements']['watermark'])
            && $template['placements']['watermark'] !== null) {
            $assetId = $template['placements']['watermark'];
            if (!isset($assets[$assetId])) {
                throw new RuntimeException('Watermark asset unavailable');
            }
            drawSlotIfPresent($pdf, $assets[$assetId], 60, 30, 90, 80, 0.15);
        }

        if ($side === 0) {
            foreach ([['front_left', 10.0], ['front_right', 180.0]] as [$slot, $x]) {
                $assetId = $template['placements'][$slot] ?? null;
                if ($assetId !== null) {
                    if (!isset($assets[$assetId])) {
                        throw new RuntimeException('Image asset unavailable');
                    }
                    drawSlotIfPresent($pdf, $assets[$assetId], $x, 5, 20, 18);
                }
            }
        } else {
            $assetId = $template['placements']['back'] ?? null;
            if ($assetId !== null) {
                if (!isset($assets[$assetId])) {
                    throw new RuntimeException('Image asset unavailable');
                }
                drawSlotIfPresent($pdf, $assets[$assetId], 180, 5, 20, 18);
            }
        }

        drawSampleHeading($pdf);
        foreach ($fields as $index => $field) {
            $style = $template['styles'][$field] ?? defaults();
            drawFieldPanel($pdf, $field, $values[$field], $style, 25 + ($index * 29), $labels);
        }

        if ($side === 1) {
            // TCPDF's PDF417 implementation consumes the string byte-for-byte
            // in byte compaction for UTF-8 data and emits a real symbol. A
            // white padded background supplies a quiet zone in the reserved
            // public envelope.
            $pdf->setRTL(false);
            $pdf->setAlpha(1.0);
            $pdf->write2DBarcode(
                $values['reference'],
                'PDF417,8,2',
                20,
                113,
                170,
                28,
                [
                    'border' => false,
                    'padding' => 2,
                    'fgcolor' => [0, 0, 0],
                    'bgcolor' => [255, 255, 255],
                ],
                '',
                false
            );
        }
    }

    $data = $pdf->Output('', 'S');
    if (!is_string($data) || !str_starts_with($data, '%PDF-') || !str_contains($data, '%%EOF')) {
        throw new RuntimeException('Incomplete PDF');
    }
    return $data;
}
