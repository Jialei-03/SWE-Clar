<?php
// Protected environment capability fixture; no task business logic.
if (PHP_SAPI === 'cli-server') {
    session_start();
    if ($_SERVER['REQUEST_METHOD']==='POST') {
        $data=file_get_contents($_FILES['image']['tmp_name']);
        $im=imagecreatefromstring($data);
        header('Content-Type: application/json');
        echo json_encode(['session'=>$_SESSION['value']??null,'width'=>imagesx($im),'height'=>imagesy($im),'sha256'=>hash('sha256',$data)]);
    } else {
        $_SESSION['value']='synthetic-session';
        echo '<form method="post" enctype="multipart/form-data"><input type="file" name="image"><button>Upload</button></form>';
    }
    exit;
}
$directory=$argv[1];
require getenv('TCPDF_ROOT').'/tcpdf.php';
$db=new SQLite3($directory.'/probe.sqlite');
$db->exec('CREATE TABLE probe(value TEXT NOT NULL)');
$db->exec("INSERT INTO probe VALUES('synthetic-value')");$db->close();
$db=new SQLite3($directory.'/probe.sqlite');
if($db->querySingle('SELECT value FROM probe')!=='synthetic-value')throw new Exception('persistence');
$im=imagecreatetruecolor(40,30);imagefill($im,0,0,imagecolorallocate($im,12,96,192));imagepng($im,$directory.'/probe.png');
$pdf=new TCPDF('L','mm',[210,148],true,'UTF-8',false);
$pdf->setPrintHeader(false);$pdf->setPrintFooter(false);$pdf->SetMargins(10,10,10);$pdf->SetAutoPageBreak(false);
$pdf->SetCreator('Independent environment probe');$pdf->SetAuthor('');$pdf->SetTitle('SAMPLE - NOT VALID');
foreach([0,1] as $side){
    $pdf->AddPage('L',[210,148]);$pdf->SetFont('dejavusans','B',14);$pdf->SetXY(35,8);$pdf->Cell(140,10,'SAMPLE / NOT VALID',0,0,'C');
    $pdf->Image($directory.'/probe.png',10,5,20,15,'PNG');
    $pdf->SetFont('dejavusans','',8);$pdf->SetXY(10,25);$pdf->Cell(85,5,'Données de démonstration');
    $pdf->setRTL(true);$pdf->SetXY(10,25);$pdf->Cell(85,5,'بيانات تجريبية',0,0,'R');$pdf->setRTL(false);
    $pdf->SetFont('dejavusans','',12);
    foreach([31,57,83] as $y){$pdf->SetXY(10,$y);$pdf->MultiCell(190,6,str_repeat('W',160),0,'L');}
    if($side===1)$pdf->write2DBarcode('SYN-REF-é-001','PDF417',20,113,170,28,['border'=>false,'padding'=>2,'fgcolor'=>[0,0,0],'bgcolor'=>[255,255,255]],'N');
}
$bytes=$pdf->Output('','S');file_put_contents($directory.'/probe.pdf',$bytes);
echo json_encode(['php'=>PHP_VERSION,'sqlite'=>SQLite3::version()['versionString'],'bcmath'=>extension_loaded('bcmath'),'gd'=>extension_loaded('gd'),'mbstring'=>extension_loaded('mbstring'),'pdf_bytes'=>strlen($bytes)]);
