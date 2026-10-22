<?php
declare(strict_types=1);
function rgb(string $color):array {return [hexdec(substr($color,1,2)),hexdec(substr($color,3,2)),hexdec(substr($color,5,2))];}
function renderPDF(array $values,array $template,array $assets,string $kind):string {
    if(!defined('K_TCPDF_THROW_EXCEPTION_ERROR'))define('K_TCPDF_THROW_EXCEPTION_ERROR',true);
    require_once getenv('TCPDF_ROOT').'/tcpdf.php';
    $pdf=new TCPDF('L','mm',[210,148],true,'UTF-8',false);
    $pdf->setPrintHeader(false);$pdf->setPrintFooter(false);$pdf->SetMargins(10,10,10);$pdf->SetAutoPageBreak(false);
    $pdf->SetCreator('Clar-SWE synthetic document application');$pdf->SetAuthor('');$pdf->SetTitle('SAMPLE - NOT VALID');
    $labels=['document_id'=>['Identifiant','المعرّف'],'name'=>['Nom','الاسم'],'group'=>['Groupe','المجموعة'],'contact'=>['Contact','جهة الاتصال'],'reviewer'=>['Révision','المراجعة'],'reference'=>['Référence','المرجع']];
    foreach([array_slice(FIELDS,0,3),array_slice(FIELDS,3,3)] as $side=>$fields){
        $pdf->AddPage('L',[210,148]);
        $pdf->SetTextColor(0,0,0);$pdf->SetFont('dejavusans','B',14);$pdf->SetXY(35,8);$pdf->Cell(140,10,'SAMPLE / NOT VALID',0,0,'C');
        foreach($fields as $i=>$field){
            // The existing preview uses default text settings. Template integration is unfinished.
            $style=defaults();$y=25+$i*29;
            if($style['background']!==null){$pdf->SetFillColor(...rgb($style['background']));$pdf->Rect(10,$y,190,29,'F');}
            if($style['border']){$pdf->SetDrawColor(0,0,0);$pdf->Rect(10,$y,190,29,'D');}
            $pdf->SetTextColor(0,0,0);$pdf->SetFont('dejavusans','',8);$pdf->SetXY(10,$y);$pdf->Cell(90,5,$labels[$field][0]);
            $pdf->setRTL(true);$pdf->SetXY(10,$y);$pdf->Cell(90,5,$labels[$field][1],0,0,'R');$pdf->setRTL(false);
            $pdf->SetTextColor(...rgb($style['color']));$pdf->SetFont('dejavusans',$style['weight']==='bold'?'B':'',$style['font_size']);
            $rtl=(bool)preg_match('/^[^\p{L}]*\p{Arabic}/u',$values[$field]);$pdf->setRTL($rtl);$pdf->SetXY(10,$y+5);$pdf->MultiCell(190,6,$values[$field],0,$rtl?'R':'L');$pdf->setRTL(false);
        }
    }
    $data=$pdf->Output('','S');if(!str_starts_with($data,'%PDF-')||!str_contains($data,'%%EOF'))throw new RuntimeException('Incomplete PDF');return $data;
}
