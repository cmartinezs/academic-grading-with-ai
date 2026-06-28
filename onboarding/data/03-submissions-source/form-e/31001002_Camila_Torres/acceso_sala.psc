Algoritmo AccesoSala
	Definir cupos Como Entero
	Definir confirma Como Caracter
	Escribir "Ingrese cupos disponibles"
	Leer cupos
	Escribir "Confirma asistencia SI o NO"
	Leer confirma
	Si cupos > 0 Y confirma = "SI" Entonces
		Escribir "Acceso permitido"
	SiNo
		Escribir "Acceso no permitido"
	FinSi
	Escribir "Fin del proceso"
FinAlgoritmo
