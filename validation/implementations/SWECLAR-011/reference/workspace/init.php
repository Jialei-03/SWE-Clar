<?php
require __DIR__.'/storage.php';
initDatabase(in_array('--reset',$argv,true));
echo "Synthetic workspace initialized.\n";
