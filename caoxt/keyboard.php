<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
 <html>
 <head>
 <title>New Document</title>
 <meta http-equiv="content-type" content="text/html; charset=utf8" />

 <style type="text/css">
 <!--
 *{margin:0;padding:0;}
 body{margin:0 auto; text-align:center;}
 .mantel{width:80%;margin:5em auto;text-align:center;}
 .num{float:left;}
 .alpha{float:left;}
 input[type=submit]{
 float:left;
 width:4em;
 height:4em;
 border:4px outset silver;
 background-color:silver;
 }

 input[type=submit]:focus{
 border:4px inset silver;
 }
 br{
 clear:both;
 }
 //-->
 </style>
 </head>
 <body>
 <div class='mantel'>

 <?php
 $num=array("^",1,2,3,4,5,6,7,8,9,0,"ß");
 $alpha=array('q','w','e','r','t','z','u','i','o','p','ü','+','a','s','d','f','g','h','j','k','l','m','ö','#');

 echo "
 <form method='post' action='".$_SERVER['php-self']."'/>
 <div class='num'>";
 foreach($num as $taste)
 echo "
 <input type='submit' name='taste[]' value='".$taste."' />
 ";
 echo "
 </div>
 <br />
 <div class='alpha'>";
 $count=0;
 foreach($alpha as $taste){
 echo "
 <input type='submit' name='taste[]' value='".$taste."' />
 ";
 $count++;
 if($count==12){
 $count=0;
 echo "<br />";
 }
 }
 echo "</div>";
 ?>
 </div>
 </body>
 </html>