<?php

$o_head = "Statistik 1";
$o_navi = "";

if($usr_rights)
  {
	include("/pChart2.1.4/class/pDraw.class.php"); 
	include("/pChart2.1.4/class/pImage.class.php"); 
	include("/pChart2.1.4/class/pData.class.php");
	
   $db_res = mysql_query("Select hour(j.rdatum) as Zeitraum, count(hour(j.rdatum)) as Kunden, sum(j.nsumme) as Umsatz from journal J 
							where j.stadium in (8,9) and j.quelle = 3 and j.quelle_sub = 2 group by hour(j.rdatum)", $db_id);
	$number = mysql_num_rows($db_res);    
	$result = array();

	for($i=0; $i<$number; $i++) {
		array_push($result, mysql_fetch_array($db_res, MYSQL_ASSOC));
	}
   mysql_free_result($db_res);
   
	$MyData = new pData(); 
   
	foreach($result as $row)
	{
		
	}

 /* Create and populate the pData object */ 
 $MyData = new pData();   
 $MyData->addPoints(array(150,220,300,-250,-420,-200,300,200,100),"Server A"); 
 $MyData->addPoints(array(140,0,340,-300,-320,-300,200,100,50),"Server B"); 
 $MyData->setAxisName(0,"Hits"); 
 $MyData->addPoints(array("January","February","March","April","May","Juin","July","August","September"),"Months"); 
 $MyData->setSerieDescription("Months","Month"); 
 $MyData->setAbscissa("Months"); 

 /* Create the pChart object */ 
 $myPicture = new pImage(700,230,$MyData); 
 $myPicture->drawGradientArea(0,0,700,230,DIRECTION_VERTICAL,array("StartR"=>240,"StartG"=>240,"StartB"=>240,"EndR"=>180,"EndG"=>180,"EndB"=>180,"Alpha"=>100)); 
 $myPicture->drawGradientArea(0,0,700,230,DIRECTION_HORIZONTAL,array("StartR"=>240,"StartG"=>240,"StartB"=>240,"EndR"=>180,"EndG"=>180,"EndB"=>180,"Alpha"=>20)); 
 $myPicture->setFontProperties(array("FontName"=>"../fonts/pf_arma_five.ttf","FontSize"=>6)); 

 /* Draw the scale  */ 
 $myPicture->setGraphArea(50,30,680,200); 
 $myPicture->drawScale(array("CycleBackground"=>TRUE,"DrawSubTicks"=>TRUE,"GridR"=>0,"GridG"=>0,"GridB"=>0,"GridAlpha"=>10)); 

 /* Turn on shadow computing */  
 $myPicture->setShadow(TRUE,array("X"=>1,"Y"=>1,"R"=>0,"G"=>0,"B"=>0,"Alpha"=>10)); 

 /* Draw the chart */ 
 $settings = array("Gradient"=>TRUE,"DisplayPos"=>LABEL_POS_INSIDE,"DisplayValues"=>TRUE,"DisplayR"=>255,"DisplayG"=>255,"DisplayB"=>255,"DisplayShadow"=>TRUE,"Surrounding"=>10); 
 $myPicture->drawBarChart($settings); 

 /* Write the chart legend */ 
 $myPicture->drawLegend(580,12,array("Style"=>LEGEND_NOBORDER,"Mode"=>LEGEND_HORIZONTAL)); 

 /* Render the picture (choose the best way) */ 
 $myPicture->autoOutput("pictures/example.drawBarChart.shaded.png"); 
	  
	  
  }
else
  {
    $o_cont="<br><br><br><br><table width=\"100%\" height=\"100%\"><tr><td align=\"center\" valign=\"middle\">@@login@@</td></tr></table><br><br><br><br>";
  }

?>