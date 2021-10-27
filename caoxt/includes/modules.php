<?php

if (!function_exists("scandir")) {
	function scandir($dir = './', $sort = 0) {
		$dir_open = @opendir($dir);
		if (! $dir_open) return false;
		while (($dir_content = readdir($dir_open)) !== false) $files[] = $dir_content;
		if ($sort == 1) rsort($files, SORT_STRING);
		else sort($files, SORT_STRING);
		return $files;
	}
}

if(!$_SESSION['m_list']) {
	$_SESSION['m_list'] = scandir('modules');
}

if(!$module) {
	include(realpath("modules/home.php"));
} else {
	$m_file = $module.".php";
	if(in_array($m_file, $_SESSION['m_list'])) {
		include(realpath("modules/".$m_file));
	} else {
		include(realpath("modules/home.php"));
	}
}

?>